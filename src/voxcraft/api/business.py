"""业务 API：/asr /tts /tts/clone /separate（全异步，ADR-011 + ADR-013）。

HTTP 端点仅做：参数校验 → 落盘上传 → 写 Job(pending) → 派发后台 task → 返回 {job_id, status}。
真正推理由 `run_job` 协程驱动：
  1. 读 DB + snapshot provider 配置
  2. 打包 JobRequest
  3. `scheduler.submit(req)` —— 后端（InProcess / Pool）实现真实执行
  4. 按 JobResult + kind 写回 DB + SSE

状态流转：pending → running → succeeded | failed | cancelled
每次状态变化通过 EventBus 发 `job_status_changed`，SSE 下发前端。
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlmodel import Session, select

from voxcraft.api.schemas.job import JobSubmitResponse
from voxcraft.api.schemas.tts import TtsRequest, VoiceSchema, VoicesResponse
from voxcraft.config import get_settings
from voxcraft.db.engine import get_engine
from voxcraft.db.models import Job, Provider, VoiceRef
from voxcraft.errors import ValidationError, VoxCraftError
from voxcraft.events.bus import Event, EventBus
from voxcraft.runtime.scheduler_api import JobRequest, JobResult


log = structlog.get_logger()
router = APIRouter(tags=["business"])


def get_session():
    with Session(get_engine()) as s:
        yield s


# ---------- 辅助 ----------

def _select_provider(
    session: Session,
    kind: str | tuple[str, ...],
    name: str | None,
) -> Provider:
    """按 kind（单值或多值）+ name 查 enabled Provider。

    多 kind 用于业务场景：TTS 路由需要 tts + cloning 共用——cloning 模型本身
    能做合成（CloningProvider 是 TtsProvider 的子类），UI 把它们合并展示，
    路由层也要兼容查询。

    语义：
    - name 显式给定：跨所有候选 kind 按 name 查（name 在 Provider 表唯一）
    - name 缺省：只取**首选 kind**（kinds[0]）的 default，避免跨 kind 默认歧义
    """
    kinds: tuple[str, ...] = (kind,) if isinstance(kind, str) else kind
    if name:
        q = select(Provider).where(
            Provider.kind.in_(kinds),  # type: ignore[attr-defined]
            Provider.enabled == True,  # noqa: E712
            Provider.name == name,
        )
    else:
        q = select(Provider).where(
            Provider.kind == kinds[0],
            Provider.enabled == True,  # noqa: E712
            Provider.is_default == True,  # noqa: E712
        )
    row = session.exec(q).first()
    if row is None:
        kind_label = kinds[0] if len(kinds) == 1 else "/".join(kinds)
        raise ValidationError(
            f"No {kind_label} provider available"
            + (f" named {name}" if name else " (no default)"),
            details={"kind": list(kinds), "requested": name},
        )
    return row


def _uploads_dir() -> Path:
    d = get_settings().output_dir / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _outputs_dir() -> Path:
    d = get_settings().output_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_upload(
    upload: UploadFile, job_id: str, suffix_hint: str = ".bin",
) -> tuple[Path, int]:
    """返回 (dest_path, size_bytes)，供调用方写入 Job.request.source_size_bytes。"""
    suffix = Path(upload.filename or "upload").suffix or suffix_hint
    dest = _uploads_dir() / f"{job_id}{suffix}"
    data = upload.file.read()
    dest.write_bytes(data)
    return dest, len(data)


async def _publish_status(
    bus: EventBus | None,
    *,
    job_id: str,
    kind: str,
    status: str,
    error_code: str | None = None,
) -> None:
    if bus is None:
        return
    payload: dict = {"job_id": job_id, "kind": kind, "status": status}
    if error_code:
        payload["error_code"] = error_code
    await bus.publish(Event(type="job_status_changed", payload=payload))


# ---------- HTTP 端点：提交入队 ----------

@router.post("/asr", response_model=JobSubmitResponse, status_code=202)
async def submit_asr(
    request: Request,
    audio: UploadFile = File(...),
    language: str | None = Form(None),
    provider: str | None = Form(None),
    # OpenAI 对齐字段（同名透传到 /v1/audio/transcriptions 也用这些）：
    prompt: str | None = Form(None, description="OpenAI 字段 → 映射到 initial_prompt"),
    temperature: float | None = Form(None),
    # faster-whisper 调优扩展（OpenAI 不暴露，但精度调优常用）：
    beam_size: int | None = Form(None),
    condition_on_previous_text: bool | None = Form(None),
    compression_ratio_threshold: float | None = Form(None),
    log_prob_threshold: float | None = Form(None),
    no_speech_threshold: float | None = Form(None),
    vad_filter: bool | None = Form(None),
    word_timestamps: bool | None = Form(None),
    session: Session = Depends(get_session),
) -> JobSubmitResponse:
    p_row = _select_provider(session, kind="asr", name=provider)
    job_id = str(uuid.uuid4())
    source_path, source_size = _save_upload(audio, job_id, ".wav")
    now = datetime.now(UTC)

    # 收集所有非 None 调优字段写入 Job.request；worker 端只取非空
    req_data: dict = {
        "source_filename": audio.filename,
        "source_size_bytes": source_size,
        "language": language,
    }
    if prompt is not None:
        req_data["initial_prompt"] = prompt  # OpenAI 命名 → faster-whisper 命名
    for k, v in (
        ("temperature", temperature),
        ("beam_size", beam_size),
        ("condition_on_previous_text", condition_on_previous_text),
        ("compression_ratio_threshold", compression_ratio_threshold),
        ("log_prob_threshold", log_prob_threshold),
        ("no_speech_threshold", no_speech_threshold),
        ("vad_filter", vad_filter),
        ("word_timestamps", word_timestamps),
    ):
        if v is not None:
            req_data[k] = v

    session.add(
        Job(
            id=job_id, kind="asr", status="pending",
            provider_name=p_row.name,
            request=req_data,
            source_path=str(source_path),
            progress=0.0, created_at=now,
        )
    )
    session.commit()
    await _publish_status(
        request.app.state.event_bus, job_id=job_id, kind="asr", status="pending",
    )
    asyncio.create_task(run_job(job_id, request.app.state))
    return JobSubmitResponse(job_id=job_id, status="pending")


@router.post("/tts", response_model=JobSubmitResponse, status_code=202)
async def submit_tts(
    request: Request,
    body: TtsRequest,
    session: Session = Depends(get_session),
) -> JobSubmitResponse:
    # cloning Provider 也是 TtsProvider 子类，UI 合并展示；路由层同时接受两 kind
    p_row = _select_provider(session, kind=("tts", "cloning"), name=body.provider)
    job_id = str(uuid.uuid4())
    now = datetime.now(UTC)

    session.add(
        Job(
            id=job_id, kind="tts", status="pending",
            provider_name=p_row.name,
            request={
                "text": body.text,
                "voice_id": body.voice_id,
                "speed": body.speed,
                "format": body.format,
            },
            progress=0.0, created_at=now,
        )
    )
    session.commit()
    await _publish_status(
        request.app.state.event_bus, job_id=job_id, kind="tts", status="pending",
    )
    asyncio.create_task(run_job(job_id, request.app.state))
    return JobSubmitResponse(job_id=job_id, status="pending")


@router.post("/tts/clone", response_model=JobSubmitResponse, status_code=202)
async def submit_clone(
    request: Request,
    text: str = Form(..., min_length=1, max_length=10000),
    reference_audio: UploadFile = File(...),
    speaker_name: str | None = Form(None),
    provider: str | None = Form(None),
    session: Session = Depends(get_session),
) -> JobSubmitResponse:
    p_row = _select_provider(session, kind="cloning", name=provider)
    job_id = str(uuid.uuid4())
    source_path, source_size = _save_upload(reference_audio, job_id, ".wav")
    now = datetime.now(UTC)

    session.add(
        Job(
            id=job_id, kind="clone", status="pending",
            provider_name=p_row.name,
            request={
                "text": text,
                "speaker_name": speaker_name,
                "reference_filename": reference_audio.filename,
                "source_size_bytes": source_size,
            },
            source_path=str(source_path),
            progress=0.0, created_at=now,
        )
    )
    session.commit()
    await _publish_status(
        request.app.state.event_bus, job_id=job_id, kind="clone", status="pending",
    )
    asyncio.create_task(run_job(job_id, request.app.state))
    return JobSubmitResponse(job_id=job_id, status="pending")


@router.post("/separate", response_model=JobSubmitResponse, status_code=202)
async def submit_separate(
    request: Request,
    audio: UploadFile = File(...),
    provider: str | None = Form(None),
    session: Session = Depends(get_session),
) -> JobSubmitResponse:
    p_row = _select_provider(session, kind="separator", name=provider)
    job_id = str(uuid.uuid4())
    source_path, source_size = _save_upload(audio, job_id, ".wav")
    now = datetime.now(UTC)

    session.add(
        Job(
            id=job_id, kind="separate", status="pending",
            provider_name=p_row.name,
            request={
                "source_filename": audio.filename,
                "source_size_bytes": source_size,
            },
            source_path=str(source_path),
            progress=0.0, created_at=now,
        )
    )
    session.commit()
    await _publish_status(
        request.app.state.event_bus, job_id=job_id, kind="separate", status="pending",
    )
    asyncio.create_task(run_job(job_id, request.app.state))
    return JobSubmitResponse(job_id=job_id, status="pending")


# ---------- 只读：可用声音列表 ----------

@router.get("/tts/voices", response_model=VoicesResponse)
async def list_voices(session: Session = Depends(get_session)):
    """返回全部可用音色，前端按 provider_name 过滤渲染。

    两类 source：
    - `preset`：非克隆 TTS（如 Piper）自带的单音色；id = Provider 名
    - `cloned`：来自 VoiceRef（声纹克隆页动态生成）

    克隆型 Provider（声明 CAPABILITIES 含 "clone"）**不** 产出 preset 条目——
    其音色仅来自 VoiceRef。
    """
    voices: list[VoiceSchema] = []

    providers = session.exec(
        select(Provider).where(
            Provider.enabled == True,  # noqa: E712
            Provider.kind.in_(["tts", "cloning"]),  # type: ignore[attr-defined]
        )
    ).all()
    for p in providers:
        if _provider_supports_clone(p.class_name):
            # 克隆型 Provider：没有内置预设音色
            continue
        voices.append(VoiceSchema(
            id=p.name, language="zh",
            provider_name=p.name, source="preset",
        ))

    for v in session.exec(select(VoiceRef)).all():
        voices.append(VoiceSchema(
            id=v.id, language="zh",
            provider_name=v.provider_name, source="cloned",
            # 试听端点：浏览器直连读流；只对 vx_ 前缀生效（见 voices.get_voice_sample）
            sample_url=f"/api/tts/voices/{v.id}/sample",
        ))
    return VoicesResponse(voices=voices)


def _provider_supports_clone(class_name: str) -> bool:
    """是否是克隆型 Provider。查 registry 获取 CAPABILITIES；unknown class 保守视为非克隆。"""
    from voxcraft.providers import capabilities
    from voxcraft.providers.registry import PROVIDER_REGISTRY
    cls = PROVIDER_REGISTRY.get(class_name)
    if cls is None:
        return False
    return capabilities.CLONE in cls.CAPABILITIES


# ---------- 后台 Runner（异步提交 + retry 共用入口）----------

async def run_job(job_id: str, app_state) -> None:
    """读 DB → 打包 JobRequest → scheduler.submit → 写回 DB + SSE。

    推理在 scheduler 后端执行（InProcess = 主进程 to_thread；Pool = 子进程）。
    本协程只负责投递 + 写回。
    """
    bus: EventBus | None = getattr(app_state, "event_bus", None)
    scheduler = app_state.scheduler

    # 1. 读 DB + snapshot Provider 配置，mark running
    with Session(get_engine()) as session:
        job = session.get(Job, job_id)
        if job is None:
            log.warning("run_job.missing", job_id=job_id)
            return
        kind = job.kind
        if job.status != "pending":
            log.warning("run_job.bad_status", job_id=job_id, status=job.status)
            return

        if kind == "video_translate":
            # 视频翻译是多 Provider 编排，绕开单 Provider 查询路径
            from voxcraft.api.video_translate import build_video_translate_request

            try:
                req = build_video_translate_request(
                    session, job, str(_outputs_dir()),
                )
            except VoxCraftError as e:
                await _finalize_failure(
                    bus, job_id, kind, code=e.code, message=e.message,
                )
                return
        else:
            p_row = session.exec(
                select(Provider).where(
                    Provider.kind == _kind_to_provider_kind(kind),
                    Provider.name == job.provider_name,
                    Provider.enabled == True,  # noqa: E712
                )
            ).first()
            if p_row is None:
                await _finalize_failure(
                    bus, job_id, kind,
                    code="PROVIDER_NOT_FOUND",
                    message=f"Provider disappeared: {job.provider_name}",
                )
                return

            req = JobRequest(
                job_id=job_id,
                kind=kind,  # type: ignore[arg-type]
                provider_name=p_row.name,
                class_name=p_row.class_name,
                provider_config=dict(p_row.config or {}),
                request_meta=dict(job.request or {}),
                source_path=job.source_path,
                output_dir=str(_outputs_dir()),
            )

        job.status = "running"
        job.started_at = datetime.now(UTC)
        session.add(job)
        session.commit()

    await _publish_status(bus, job_id=job_id, kind=kind, status="running")

    # 2. 投递给后端 scheduler 执行
    try:
        result: JobResult = await scheduler.submit(req)
    except BaseException as e:  # noqa: BLE001
        # scheduler 自身故障（worker 崩溃等）——极少数情况
        await _finalize_failure(
            bus, job_id, kind,
            code="INTERNAL_ERROR", message=f"{type(e).__name__}: {e}",
        )
        return

    # 3. 写回 DB（若期间用户 cancel 已写 cancelled，不覆盖）
    if not result.ok:
        await _finalize_failure(
            bus, job_id, kind,
            code=result.error_code or "INFERENCE_ERROR",
            message=result.error_message or "Inference failed",
        )
        return

    await _finalize_success(bus, job_id, kind, result, req)


async def _finalize_video_translate_warnings(job_id: str, warnings: list[str]) -> None:
    """把 orchestrator 返回的软降级 warnings 写入 Job.warnings。"""
    if not warnings:
        return
    with Session(get_engine()) as session:
        j = session.get(Job, job_id)
        if j is None:
            return
        j.warnings = warnings
        session.add(j)
        session.commit()


def _kind_to_provider_kind(kind: str) -> str:
    # Job.kind ∈ {asr, tts, clone, separate}；Provider.kind ∈ {asr, tts, cloning, separator}
    return {"clone": "cloning", "separate": "separator"}.get(kind, kind)


async def _finalize_failure(
    bus: EventBus | None, job_id: str, kind: str, *, code: str, message: str,
) -> None:
    with Session(get_engine()) as session:
        j = session.get(Job, job_id)
        if j is None or j.status == "cancelled":
            # 用户期间已 DELETE + cancel；不覆盖
            return
        j.status = "failed"
        j.error_code = code
        j.error_message = message
        j.finished_at = datetime.now(UTC)
        session.add(j)
        session.commit()
    log.warning("run_job.failed", job_id=job_id, kind=kind, code=code, msg=message)
    await _publish_status(
        bus, job_id=job_id, kind=kind, status="failed", error_code=code,
    )


async def _finalize_success(
    bus: EventBus | None,
    job_id: str,
    kind: str,
    result: JobResult,
    req: JobRequest,
) -> None:
    with Session(get_engine()) as session:
        j = session.get(Job, job_id)
        if j is None or j.status == "cancelled":
            return

        # Clone 特殊：新增 VoiceRef + 把 voice_id 合入 request
        if kind == "clone" and result.voice_id:
            existing = session.get(VoiceRef, result.voice_id)
            if existing is None:
                suffix = Path(req.source_path).suffix if req.source_path else ".wav"
                ref_final = _outputs_dir() / "voices" / f"{result.voice_id}{suffix}"
                session.add(
                    VoiceRef(
                        id=result.voice_id,
                        speaker_name=req.request_meta.get("speaker_name"),
                        reference_audio_path=str(ref_final),
                        provider_name=req.provider_name,
                    )
                )
            j.request = {**(j.request or {}), "voice_id": result.voice_id}

        # video_translate：把 result["warnings"] 写入 Job.warnings
        if kind == "video_translate" and result.result:
            warns = result.result.get("warnings")
            if isinstance(warns, list) and warns:
                j.warnings = list(warns)

        # 产物大小：main + extras（用于前端 badge 直接显示，避免额外 HEAD 请求）
        artifact_sizes: dict[str, int] = {}
        paths: dict[str, str] = {}
        if result.output_extras:
            paths.update({k: v for k, v in result.output_extras.items() if v})
        if result.output_path and result.output_path not in paths.values():
            paths["main"] = result.output_path
        for k, p in paths.items():
            try:
                artifact_sizes[k] = Path(p).stat().st_size
            except OSError:
                pass

        merged_result: dict | None = None
        if result.result is not None or artifact_sizes:
            merged_result = dict(result.result or {})
            if artifact_sizes:
                merged_result["artifact_sizes"] = artifact_sizes

        j.status = "succeeded"
        j.result = merged_result
        j.output_path = result.output_path
        j.output_extras = result.output_extras
        j.progress = 1.0
        j.finished_at = datetime.now(UTC)
        session.add(j)
        session.commit()
    await _publish_status(bus, job_id=job_id, kind=kind, status="succeeded")
