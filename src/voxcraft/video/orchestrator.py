"""视频语音级翻译编排器（ADR-014 §8 / v0.4.0）。

5 阶段串行：demux → asr → translate → tts → mux

本模块是 **纯同步**：worker_runners 在 scheduler 的线程/进程里驱动；不依赖
asyncio 事件循环。LRU 由调用方（worker）传入，orchestrator 按顺序
ensure_loaded(asr) → ensure_loaded(tts)，LRU 内部自动 unload 上一个，
维持单模型驻留（ADR-008）。

多段 LLM 翻译采用 **软降级**（ADR-014 §8.1）：空/markdown/膨胀/元信息泄漏
→ 用原文回退 + 写 warnings，不让整个 Job 失败。

产物：scratch 目录在 finally 清理；outputs 目录保留 SRT/音频/视频三路。
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

# 注：上面的 dataclass 也被 _TranslateOutcome（见 Stage 翻译段）使用

import structlog

from voxcraft.errors import (
    InferenceError,
    LlmApiError,
    MediaDecodeError,
    VoxCraftError,
)
from voxcraft.providers.base import AsrProvider, TtsProvider
from voxcraft.providers.registry import instantiate
from voxcraft.runtime.scheduler_api import JobRequest, JobResult
from voxcraft.video.alignment import (
    SourceSegment,
    finalize_alignment,
    plan_alignment,
    wav_duration,
)
from voxcraft.video.ffmpeg_io import concat_audio, extract_audio, mux_video, probe
from voxcraft.video.subtitle import SrtSegment, segments_to_srt


log = structlog.get_logger()


# 5 阶段进度占比（ADR-014 §8）
STAGE_WEIGHTS = {
    "demux": 0.05,
    "asr": 0.35,
    "translate": 0.10,
    "tts": 0.40,
    "mux": 0.10,
}

_STAGE_ORDER = ("demux", "asr", "translate", "tts", "mux")


# 翻译护栏（位于用户 prompt 之后，ADR-014 §2）
_GUARD_SUFFIX = (
    "\n\nOutput only the translation. Do not add explanations, "
    "markdown formatting, code fences, or quotation marks."
)

_DEFAULT_SYSTEM_PROMPT_TEMPLATE = (
    "You are a professional subtitle translator. "
    "Translate from {source_lang} to {target_lang}. "
    "Preserve punctuation, tone, and numbers. "
    "Keep each output roughly the same length as the source."
)


class LruLike(Protocol):
    def ensure_loaded(self, target): ...  # noqa: ANN001, D401, E501


class LlmChatFn(Protocol):
    def __call__(self, messages: list[dict], *, model: str | None = None) -> str: ...


# ---------- 公共数据 ----------

@dataclass
class OrchestratorResult:
    audio_path: str
    subtitle_path: str
    video_path: str | None
    warnings: list[str] = field(default_factory=list)


EmitFn = Callable[[dict], None]


# ---------- 入口 ----------

def run_video_translate(
    req: JobRequest,
    lru: LruLike,
    emit: EmitFn | None = None,
    *,
    llm_chat_fn: LlmChatFn | None = None,
) -> JobResult:
    """阶段 3 主入口：执行完整编排，返回 JobResult。

    `llm_chat_fn` 可注入 mock（测试）；默认根据 request_meta.llm 构造 LlmClient。
    """
    meta = req.request_meta
    scratch_dir = Path(req.output_dir) / "scratch" / req.job_id
    out_dir = Path(req.output_dir) / "outputs" / req.job_id

    warnings: list[str] = []
    try:
        scratch_dir.mkdir(parents=True, exist_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)

        progress = _ProgressTracker(req, emit)
        chat_fn = llm_chat_fn or _build_llm_chat_fn(meta.get("llm", {}))

        # ---- Stage 1/5 · demux ----
        progress.stage_started("demux")
        source_path = req.source_path
        assert source_path, "video_translate requires source_path"
        info = probe(source_path)
        is_video = info.is_video
        audio_path = scratch_dir / "source.wav"
        extract_audio(source_path, audio_path)
        progress.stage_done("demux")

        # ---- Stage 2/5 · ASR ----
        progress.stage_started("asr")
        asr_inst = _instantiate_provider(meta["asr"])
        assert isinstance(asr_inst, AsrProvider), "asr provider kind mismatch"
        lru.ensure_loaded(asr_inst)
        asr_result = asr_inst.transcribe(
            str(audio_path),
            language=meta.get("source_lang"),
            progress_cb=progress.stage_sub_cb("asr"),
        )
        segments_raw = asr_result.segments
        if not segments_raw:
            raise InferenceError("ASR produced no segments")
        progress.stage_done("asr")

        # ---- Stage 3/5 · 翻译 ----
        progress.stage_started("translate")
        translate_outcomes = _translate_segments(
            segments_raw,
            source_lang=meta.get("source_lang") or asr_result.language,
            target_lang=meta["target_lang"],
            system_prompt=meta.get("system_prompt"),
            llm_chat_fn=chat_fn,
            warnings=warnings,
            llm_config=meta.get("llm", {}),
            max_inflation_ratio=float(meta.get("translate_max_inflation", 5.0)),
        )
        progress.stage_done("translate")

        # ---- 时间轴对齐（plan 阶段）----
        source_segs = [
            SourceSegment(
                index=i + 1, start=s.start, end=s.end,
                text=translate_outcomes[i].final_text,
            )
            for i, s in enumerate(segments_raw)
        ]
        planned = plan_alignment(
            source_segs,
            mode=meta.get("align_mode", "natural"),
            max_speedup=float(meta.get("align_max_speedup", 1.3)),
        )

        # ---- Stage 4/5 · TTS ----
        progress.stage_started("tts")
        tts_inst = _instantiate_provider(meta["tts"])
        assert isinstance(tts_inst, TtsProvider), "tts provider kind mismatch"
        lru.ensure_loaded(tts_inst)

        # clone_voice：若开启且 Provider 是 CloningProvider，用原音频做 zero-shot 克隆
        voice_id: str = tts_inst.name
        if meta.get("clone_voice") and _is_cloning_provider(tts_inst):
            voice_id = _prepare_clone_voice(tts_inst, str(audio_path))

        seg_audio_paths: list[Path] = []
        measured_durations: list[float] = []
        total = len(planned)
        for idx, p in enumerate(planned):
            audio_bytes = tts_inst.synthesize(
                p.text, voice_id=voice_id, speed=p.speed, format="wav",
            )
            path = scratch_dir / f"seg_{idx:04d}.wav"
            path.write_bytes(audio_bytes)
            seg_audio_paths.append(path)
            # 实测时长；失败回退到估算
            try:
                measured_durations.append(wav_duration(path))
            except Exception:  # noqa: BLE001
                measured_durations.append(
                    max(0.3, p.estimated_duration / max(1.0, p.speed)),
                )
            progress.stage_sub_cb("tts")((idx + 1) / total)
        progress.stage_done("tts")

        # ---- 时间轴对齐（finalize 阶段）----
        aligned = finalize_alignment(planned, measured_durations)

        # ---- 合成产物 ----
        progress.stage_started("mux")

        # SRT：基于对齐后的时间戳
        srt_segs = [
            SrtSegment(
                index=a.index,
                start=a.final_start,
                end=a.final_end,
                text=a.text,
            )
            for a in aligned
        ]
        subtitle_path = out_dir / "subtitle.srt"
        subtitle_path.write_text(segments_to_srt(srt_segs), encoding="utf-8")

        # 译文音频
        audio_out_path = out_dir / "audio.wav"
        concat_audio(seg_audio_paths, audio_out_path)

        # 合成视频（仅视频输入）
        video_out_path: Path | None = None
        if is_video:
            video_out_path = out_dir / "video.mp4"
            mux_video(
                source_path, audio_out_path, video_out_path,
                srt_path=subtitle_path,
                subtitle_mode=meta.get("subtitle_mode", "soft"),
            )
        progress.stage_done("mux")

        output_extras = {
            "subtitle": str(subtitle_path),
            "audio": str(audio_out_path),
        }
        if video_out_path is not None:
            output_extras["video"] = str(video_out_path)

        # 主产物：视频输入 → video；音频输入 → audio
        output_path = str(video_out_path) if video_out_path else str(audio_out_path)

        # 每段对照详情：给前端详情页渲染原文/译文/对齐表 + 诊断 LLM 降级
        segments_detail = [
            {
                "index": a.index,
                "orig_start": round(segments_raw[i].start, 3),
                "orig_end": round(segments_raw[i].end, 3),
                "final_start": round(a.final_start, 3),
                "final_end": round(a.final_end, 3),
                "speed": round(a.speed, 3),
                "drift": round(a.drift, 3),
                "source_text": segments_raw[i].text,
                "translated_text": a.text,
                "untranslated": a.text.startswith("[untranslated] "),
                # 诊断字段：LLM 实际返回了什么 + 触发了哪条降级规则（若正常则 None）
                "llm_raw": translate_outcomes[i].llm_raw,
                "degrade_reason": translate_outcomes[i].degrade_reason,
            }
            for i, a in enumerate(aligned)
        ]

        return JobResult(
            ok=True,
            result={
                "language": asr_result.language,
                "duration": round(asr_result.duration, 3),
                "segment_count": len(segments_raw),
                "warnings": warnings,
                "segments": segments_detail,
            },
            output_path=output_path,
            output_extras=output_extras,
        )

    except VoxCraftError as e:
        return JobResult(ok=False, error_code=e.code, error_message=e.message)
    except AssertionError as e:
        return JobResult(
            ok=False, error_code="INTERNAL_ERROR",
            error_message=f"assertion: {e}",
        )
    except BaseException as e:  # noqa: BLE001
        return JobResult(
            ok=False,
            error_code="INTERNAL_ERROR",
            error_message=f"{type(e).__name__}: {e}",
        )
    finally:
        # 清理 scratch；outputs 保留
        if scratch_dir.exists():
            shutil.rmtree(scratch_dir, ignore_errors=True)


# ---------- Stage 翻译（含软降级） ----------

_MARKDOWN_RE = re.compile(r"```|\*\*|^#+\s|^>\s", re.MULTILINE)
_LEAK_PATTERNS = (
    "[SYSTEM]", "<thinking>", "</thinking>", "<assistant>", "<user>",
)


@dataclass(frozen=True)
class _TranslateOutcome:
    """单段翻译的结构化输出：最终文本 + LLM 原始响应 + 降级原因。"""
    final_text: str            # 写入 SRT 的文本（降级时带 [untranslated] 前缀）
    llm_raw: str | None        # LLM 实际返回（即使被判定为不合格仍保留；空段为 None）
    degrade_reason: str | None # None = 正常采纳；非空 = 降级原因（4 类之一）


def _translate_segments(
    segments, *,
    source_lang: str,
    target_lang: str,
    system_prompt: str | None,
    llm_chat_fn: LlmChatFn,
    warnings: list[str],
    llm_config: dict,
    max_inflation_ratio: float = 5.0,
) -> list[_TranslateOutcome]:
    head = system_prompt.strip() if system_prompt else (
        _DEFAULT_SYSTEM_PROMPT_TEMPLATE.format(
            source_lang=source_lang or "auto",
            target_lang=target_lang,
        )
    )
    system_msg = head + _GUARD_SUFFIX
    model = llm_config.get("model")

    out: list[_TranslateOutcome] = []
    for i, seg in enumerate(segments):
        src_text = seg.text.strip()
        if not src_text:
            warnings.append(f"segment {i}: empty source, skipped")
            out.append(_TranslateOutcome("", None, "empty source"))
            continue
        try:
            translated = llm_chat_fn(
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": src_text},
                ],
                model=model,
            )
        except LlmApiError as e:
            # 单段 LLM 失败 → 整个 Job 失败（ADR-014 §8.1）
            raise e
        raw = translated or ""
        cleaned = raw.strip()

        degraded = _degrade_or_none(cleaned, src_text, max_inflation_ratio)
        if degraded is not None:
            warnings.append(f"segment {i}: {degraded} — fell back to source text")
            out.append(_TranslateOutcome(
                final_text=f"[untranslated] {src_text}",
                llm_raw=raw,
                degrade_reason=degraded,
            ))
        else:
            out.append(_TranslateOutcome(
                final_text=cleaned,
                llm_raw=raw,
                degrade_reason=None,
            ))
    return out


def _degrade_or_none(
    translated: str, source: str, max_inflation_ratio: float = 5.0,
) -> str | None:
    """返回降级原因字符串；None = 合格。

    `max_inflation_ratio`：LLM 输出允许的最大膨胀倍数（len(out) > len(src) * ratio + 50）。
    默认 5.0 容纳常规语义膨胀；设 `0` 完全禁用此项规则（其他三条保留）。
    """
    if not translated:
        return "empty output"
    if _MARKDOWN_RE.search(translated):
        return "markdown detected"
    if max_inflation_ratio > 0 and len(translated) > len(source) * max_inflation_ratio + 50:
        return "extreme inflation"
    for pat in _LEAK_PATTERNS:
        if pat in translated:
            return f"metadata leak ({pat})"
    return None


# ---------- 内部 helpers ----------

def _instantiate_provider(spec: dict):
    return instantiate(spec["class_name"], name=spec["name"], config=spec["config"])


def _is_cloning_provider(inst) -> bool:
    from voxcraft.providers.base import CloningProvider
    return isinstance(inst, CloningProvider)


def _prepare_clone_voice(tts_inst, reference_audio_path: str) -> str:
    """从原音轨抽一段参考音频调 clone_voice；失败不致命，回落 provider.name。"""
    try:
        return tts_inst.clone_voice(reference_audio_path, speaker_name=None)
    except Exception as e:  # noqa: BLE001
        log.warning("orchestrator.clone_voice_fallback", error=str(e))
        return tts_inst.name


def _build_llm_chat_fn(llm_config: dict) -> LlmChatFn:
    """默认实现：用 LlmClient 直连。测试场景用 llm_chat_fn 注入 mock。"""
    from voxcraft.llm import LlmClient

    client = LlmClient(
        base_url=llm_config["base_url"],
        api_key=llm_config["api_key"],
        model=llm_config["model"],
    )

    def chat(messages: list[dict], *, model: str | None = None) -> str:
        return client.chat(messages, model=model)

    return chat


# ---------- 进度追踪 ----------

class _ProgressTracker:
    """按 STAGE_WEIGHTS 累积总进度并通过 emit 推 job_progress 事件。"""

    def __init__(self, req: JobRequest, emit: EmitFn | None) -> None:
        self._req = req
        self._emit = emit
        self._completed = 0.0

    def _publish(self, progress: float) -> None:
        if self._emit is None:
            return
        self._emit(
            {
                "type": "job_progress",
                "job_id": self._req.job_id,
                "kind": self._req.kind,
                "progress": max(0.0, min(1.0, progress)),
            }
        )

    def stage_started(self, name: str) -> None:
        self._publish(self._completed)

    def stage_sub_cb(self, name: str) -> Callable[[float], None]:
        weight = STAGE_WEIGHTS[name]
        base = self._completed

        def cb(p: float) -> None:
            self._publish(base + weight * max(0.0, min(1.0, p)))

        return cb

    def stage_done(self, name: str) -> None:
        self._completed += STAGE_WEIGHTS[name]
        self._publish(self._completed)
