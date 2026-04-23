"""Worker-side 推理 runner（ADR-013）。

这些函数是 **纯同步** 的：输入 JobRequest（已是 picklable），内部 instantiate Provider、
调用 transcribe/synthesize/clone_voice/separate、写产物到 output_dir，返回 JobResult。

- 不依赖主进程 DB session / asyncio event loop / EventBus
- 不持有跨任务状态；LRU 由调用方（scheduler 后端）维护
- 跨进程调用时：被 PoolScheduler 的 worker 子进程直接调
- 单进程调用时：被 InProcessScheduler 在主进程线程池中调（asyncio.to_thread）

可选 `emit_event` 回调用于实时推进度 / 自定义事件：
  - InProcess backend：闭包里用 `loop.call_soon_threadsafe(bus.publish, ...)`
  - Pool backend：闭包里 `event_q.put(dict)`，主进程 consumer 转 EventBus
事件格式：`{"type": "job_progress", "job_id", "kind", "progress": 0.0~1.0, ...}`

VoxCraftError 一律转换为 JobResult(ok=False, error_code, error_message)，不抛出；
其他异常会被外层 scheduler 捕获转换。
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from voxcraft.errors import VoxCraftError
from voxcraft.providers.base import (
    AsrProvider,
    CloningProvider,
    Provider,
    SeparatorProvider,
    TtsProvider,
)
from voxcraft.providers.registry import instantiate
from voxcraft.runtime.scheduler_api import JobRequest, JobResult


EmitFn = Callable[[dict], None]


# ---------- LRU=1（worker 内置，主进程路径也会用到同一实例） ----------

@dataclass
class _LruOne:
    """同步版 LRU=1；不依赖 asyncio（worker 单线程循环或主线程 to_thread 均可用）。"""

    current: Provider | None = None

    def ensure_loaded(self, target: Provider) -> None:
        if self.current is target and target.loaded:
            return
        if self.current is not None and self.current is not target and self.current.loaded:
            self.current.unload()
        if not target.loaded:
            target.load()
        self.current = target

    def evict(self) -> None:
        if self.current is not None and self.current.loaded:
            self.current.unload()
        self.current = None


# ---------- 入口：按 kind 分派 ----------

def run(
    req: JobRequest, lru: _LruOne, emit_event: EmitFn | None = None,
) -> JobResult:
    """同步入口。异常 → JobResult(ok=False)。

    emit_event(dict)：可选事件回调；当前 `_run_asr` 会利用它推 `job_progress`。
    """
    try:
        inst = instantiate(
            req.class_name, name=req.provider_name, config=req.provider_config,
        )
        lru.ensure_loaded(inst)
        if req.kind == "asr":
            return _run_asr(req, inst, emit_event)
        if req.kind == "tts":
            return _run_tts(req, inst)
        if req.kind == "clone":
            return _run_clone(req, inst)
        if req.kind == "separate":
            return _run_separate(req, inst)
        return JobResult(
            ok=False,
            error_code="UNKNOWN_KIND",
            error_message=f"Unknown kind: {req.kind}",
        )
    except VoxCraftError as e:
        return JobResult(ok=False, error_code=e.code, error_message=e.message)
    except BaseException as e:  # noqa: BLE001
        return JobResult(
            ok=False,
            error_code="INTERNAL_ERROR",
            error_message=f"{type(e).__name__}: {e}",
        )


def _make_progress_cb(
    req: JobRequest, emit: EmitFn | None,
) -> Callable[[float], None] | None:
    """把 emit_event 包装成 Provider 友好的 progress(float) 回调。"""
    if emit is None:
        return None

    def cb(p: float) -> None:
        emit(
            {
                "type": "job_progress",
                "job_id": req.job_id,
                "kind": req.kind,
                "progress": max(0.0, min(1.0, p)),
            }
        )

    return cb


# ---------- kind-specific runners ----------

def _run_asr(req: JobRequest, inst, emit: EmitFn | None) -> JobResult:
    assert isinstance(inst, AsrProvider)
    assert req.source_path, "ASR 必须有 source_path"
    language = req.request_meta.get("language")
    progress_cb = _make_progress_cb(req, emit)
    r = inst.transcribe(req.source_path, language=language, progress_cb=progress_cb)
    segments = [{"start": s.start, "end": s.end, "text": s.text} for s in r.segments]
    return JobResult(
        ok=True,
        result={
            "language": r.language,
            "duration": r.duration,
            "segment_count": len(segments),
            "segments": segments,
        },
    )


def _run_tts(req: JobRequest, inst) -> JobResult:
    assert isinstance(inst, TtsProvider)
    meta = req.request_meta
    text = meta["text"]
    voice_id = meta["voice_id"]
    speed = meta.get("speed", 1.0)
    fmt = meta.get("format", "wav")
    audio = inst.synthesize(text, voice_id=voice_id, speed=speed, format=fmt)

    suffix = {"wav": ".wav", "mp3": ".mp3", "ogg": ".ogg"}[fmt]
    out = Path(req.output_dir) / f"{req.job_id}{suffix}"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(audio)
    return JobResult(ok=True, output_path=str(out))


def _run_clone(req: JobRequest, inst) -> JobResult:
    assert isinstance(inst, CloningProvider)
    assert req.source_path, "Clone 必须有参考音频"
    meta = req.request_meta
    text = meta["text"]
    speaker_name = meta.get("speaker_name")

    voice_id = inst.clone_voice(req.source_path, speaker_name=speaker_name)
    audio = inst.synthesize(text, voice_id=voice_id)

    out_dir = Path(req.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ref_dir = out_dir / "voices"
    ref_dir.mkdir(parents=True, exist_ok=True)
    ref_final = ref_dir / f"{voice_id}{Path(req.source_path).suffix}"
    shutil.copy2(req.source_path, ref_final)

    out_path = out_dir / f"{req.job_id}.wav"
    out_path.write_bytes(audio)
    return JobResult(ok=True, output_path=str(out_path), voice_id=voice_id)


def _run_separate(req: JobRequest, inst) -> JobResult:
    assert isinstance(inst, SeparatorProvider)
    assert req.source_path, "Separate 必须有 source_path"
    r = inst.separate(req.source_path)

    out_dir = Path(req.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    vocals = out_dir / f"{req.job_id}-vocals.wav"
    instr = out_dir / f"{req.job_id}-instrumental.wav"
    shutil.copy2(r.vocals_path, vocals)
    shutil.copy2(r.instrumental_path, instr)
    return JobResult(
        ok=True,
        output_extras={"vocals": str(vocals), "instrumental": str(instr)},
    )
