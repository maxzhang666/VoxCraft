"""业务 API：/asr /tts /tts/clone /separate（全异步）。

HTTP 端点仅做：参数校验 → 落盘上传 → 写 Job(pending) → 派发后台 task → 返回 {job_id, status}。
真正推理在 `run_job` 协程执行（可被 /jobs/{id}/retry 复用）。

状态流转：pending → running → succeeded | failed
每次状态变化通过 EventBus 发 `job_status_changed`，SSE 下发前端。
"""
from __future__ import annotations

import asyncio
import shutil
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
from voxcraft.providers.base import (
    AsrProvider,
    CloningProvider,
    SeparatorProvider,
    TtsProvider,
)
from voxcraft.providers.registry import instantiate


log = structlog.get_logger()
router = APIRouter(tags=["business"])


def get_session():
    with Session(get_engine()) as s:
        yield s


# ---------- 辅助 ----------

def _select_provider(session: Session, kind: str, name: str | None) -> Provider:
    q = select(Provider).where(
        Provider.kind == kind, Provider.enabled == True  # noqa: E712
    )
    if name:
        q = q.where(Provider.name == name)
    else:
        q = q.where(Provider.is_default == True)  # noqa: E712
    row = session.exec(q).first()
    if row is None:
        raise ValidationError(
            f"No {kind} provider available"
            + (f" named {name}" if name else " (no default)"),
            details={"kind": kind, "requested": name},
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


def _save_upload(upload: UploadFile, job_id: str, suffix_hint: str = ".bin") -> Path:
    suffix = Path(upload.filename or "upload").suffix or suffix_hint
    dest = _uploads_dir() / f"{job_id}{suffix}"
    with dest.open("wb") as f:
        f.write(upload.file.read())
    return dest


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


def _exc_to_code_msg(exc: BaseException) -> tuple[str, str]:
    if isinstance(exc, VoxCraftError):
        return exc.code, exc.message
    return "INTERNAL_ERROR", str(exc)


# ---------- HTTP 端点：提交入队 ----------

@router.post("/asr", response_model=JobSubmitResponse, status_code=202)
async def submit_asr(
    request: Request,
    audio: UploadFile = File(...),
    language: str | None = Form(None),
    provider: str | None = Form(None),
    session: Session = Depends(get_session),
) -> JobSubmitResponse:
    p_row = _select_provider(session, kind="asr", name=provider)
    job_id = str(uuid.uuid4())
    source_path = _save_upload(audio, job_id, ".wav")
    now = datetime.now(UTC)

    session.add(
        Job(
            id=job_id, kind="asr", status="pending",
            provider_name=p_row.name,
            request={"source_filename": audio.filename, "language": language},
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
    p_row = _select_provider(session, kind="tts", name=body.provider)
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
    source_path = _save_upload(reference_audio, job_id, ".wav")
    now = datetime.now(UTC)

    session.add(
        Job(
            id=job_id, kind="clone", status="pending",
            provider_name=p_row.name,
            request={
                "text": text,
                "speaker_name": speaker_name,
                "reference_filename": reference_audio.filename,
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
    source_path = _save_upload(audio, job_id, ".wav")
    now = datetime.now(UTC)

    session.add(
        Job(
            id=job_id, kind="separate", status="pending",
            provider_name=p_row.name,
            request={"source_filename": audio.filename},
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
    rows = session.exec(
        select(Provider).where(
            Provider.enabled == True,  # noqa: E712
            Provider.kind.in_(["tts", "cloning"]),  # type: ignore[attr-defined]
        )
    ).all()
    voices: list[VoiceSchema] = []
    for v in session.exec(select(VoiceRef)).all():
        voices.append(VoiceSchema(id=v.id, language="zh", sample_url=None))
    for p in rows:
        voices.append(VoiceSchema(id=p.name, language="zh"))
    return VoicesResponse(voices=voices)


# ---------- 后台 Runner（异步提交 + retry 共用入口）----------

async def run_job(job_id: str, app_state) -> None:
    """按 kind 分发到对应 runner。在 asyncio.create_task 中调用。"""
    bus: EventBus | None = getattr(app_state, "event_bus", None)
    scheduler = app_state.scheduler
    lru = app_state.lru

    with Session(get_engine()) as session:
        job = session.get(Job, job_id)
        if job is None:
            log.warning("run_job.missing", job_id=job_id)
            return
        kind = job.kind
        if job.status != "pending":
            log.warning("run_job.bad_status", job_id=job_id, status=job.status)
            return
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
                VoxCraftError(
                    f"Provider disappeared: {job.provider_name}",
                    code="PROVIDER_NOT_FOUND",
                ),
            )
            return
        # snapshot 所需字段（session 关闭前）
        request_meta = dict(job.request or {})
        source_path = job.source_path
        class_name = p_row.class_name
        p_name = p_row.name
        p_config = dict(p_row.config or {})

        job.status = "running"
        job.started_at = datetime.now(UTC)
        session.add(job)
        session.commit()

    await _publish_status(bus, job_id=job_id, kind=kind, status="running")

    inst = instantiate(class_name, name=p_name, config=p_config)

    try:
        if kind == "asr":
            await _run_asr(job_id, inst, source_path, request_meta, scheduler, lru)
        elif kind == "tts":
            await _run_tts(job_id, inst, request_meta, scheduler, lru)
        elif kind == "clone":
            await _run_clone(job_id, inst, source_path, request_meta, scheduler, lru)
        elif kind == "separate":
            await _run_separate(job_id, inst, source_path, request_meta, scheduler, lru)
        else:
            raise VoxCraftError(f"Unknown kind: {kind}", code="UNKNOWN_KIND")
        await _publish_status(bus, job_id=job_id, kind=kind, status="succeeded")
    except BaseException as e:
        await _finalize_failure(bus, job_id, kind, e)


def _kind_to_provider_kind(kind: str) -> str:
    # Job.kind ∈ {asr, tts, clone, separate}；Provider.kind ∈ {asr, tts, cloning, separator}
    return {"clone": "cloning", "separate": "separator"}.get(kind, kind)


async def _finalize_failure(
    bus: EventBus | None, job_id: str, kind: str, exc: BaseException
) -> None:
    code, msg = _exc_to_code_msg(exc)
    with Session(get_engine()) as session:
        j = session.get(Job, job_id)
        if j is not None:
            j.status = "failed"
            j.error_code = code
            j.error_message = msg
            j.finished_at = datetime.now(UTC)
            session.add(j)
            session.commit()
    log.warning("run_job.failed", job_id=job_id, kind=kind, code=code, msg=msg)
    await _publish_status(
        bus, job_id=job_id, kind=kind, status="failed", error_code=code,
    )


# ---------- 各 kind runner ----------

async def _run_asr(job_id, inst, source_path, request_meta, scheduler, lru):
    assert isinstance(inst, AsrProvider)
    language = request_meta.get("language")

    async def run():
        await lru.ensure_loaded(inst)
        return inst.transcribe(source_path, language=language)

    result = await scheduler.run(run)
    segments = [
        {"start": s.start, "end": s.end, "text": s.text} for s in result.segments
    ]
    with Session(get_engine()) as session:
        j = session.get(Job, job_id)
        if j is None:
            return
        j.status = "succeeded"
        j.result = {
            "language": result.language,
            "duration": result.duration,
            "segment_count": len(segments),
            "segments": segments,
        }
        j.progress = 1.0
        j.finished_at = datetime.now(UTC)
        session.add(j)
        session.commit()


async def _run_tts(job_id, inst, request_meta, scheduler, lru):
    assert isinstance(inst, TtsProvider)
    text = request_meta["text"]
    voice_id = request_meta["voice_id"]
    speed = request_meta.get("speed", 1.0)
    fmt = request_meta.get("format", "wav")

    async def run():
        await lru.ensure_loaded(inst)
        return inst.synthesize(text, voice_id=voice_id, speed=speed, format=fmt)

    audio_bytes = await scheduler.run(run)
    suffix = {"wav": ".wav", "mp3": ".mp3", "ogg": ".ogg"}[fmt]
    output_path = _outputs_dir() / f"{job_id}{suffix}"
    output_path.write_bytes(audio_bytes)

    with Session(get_engine()) as session:
        j = session.get(Job, job_id)
        if j is None:
            return
        j.status = "succeeded"
        j.output_path = str(output_path)
        j.progress = 1.0
        j.finished_at = datetime.now(UTC)
        session.add(j)
        session.commit()


async def _run_clone(job_id, inst, source_path, request_meta, scheduler, lru):
    assert isinstance(inst, CloningProvider)
    text = request_meta["text"]
    speaker_name = request_meta.get("speaker_name")

    async def run():
        await lru.ensure_loaded(inst)
        voice_id = inst.clone_voice(source_path, speaker_name=speaker_name)
        audio = inst.synthesize(text, voice_id=voice_id)
        return voice_id, audio

    voice_id, audio_bytes = await scheduler.run(run)

    ref_dir = _outputs_dir() / "voices"
    ref_dir.mkdir(parents=True, exist_ok=True)
    ref_final = ref_dir / f"{voice_id}{Path(source_path).suffix}"
    shutil.copy2(source_path, ref_final)

    output_path = _outputs_dir() / f"{job_id}.wav"
    output_path.write_bytes(audio_bytes)

    with Session(get_engine()) as session:
        existing = session.get(VoiceRef, voice_id)
        if existing is None:
            session.add(
                VoiceRef(
                    id=voice_id,
                    speaker_name=speaker_name,
                    reference_audio_path=str(ref_final),
                    provider_name=inst.name,
                )
            )
        j = session.get(Job, job_id)
        if j is not None:
            j.status = "succeeded"
            j.request = {**(j.request or {}), "voice_id": voice_id}
            j.output_path = str(output_path)
            j.progress = 1.0
            j.finished_at = datetime.now(UTC)
            session.add(j)
        session.commit()


async def _run_separate(job_id, inst, source_path, request_meta, scheduler, lru):
    assert isinstance(inst, SeparatorProvider)

    async def run():
        await lru.ensure_loaded(inst)
        return inst.separate(source_path)

    result = await scheduler.run(run)
    output_dir = _outputs_dir()
    vocals_final = output_dir / f"{job_id}-vocals.wav"
    instr_final = output_dir / f"{job_id}-instrumental.wav"
    shutil.copy2(result.vocals_path, vocals_final)
    shutil.copy2(result.instrumental_path, instr_final)

    with Session(get_engine()) as session:
        j = session.get(Job, job_id)
        if j is None:
            return
        j.status = "succeeded"
        j.output_extras = {
            "vocals": str(vocals_final),
            "instrumental": str(instr_final),
        }
        j.progress = 1.0
        j.finished_at = datetime.now(UTC)
        session.add(j)
        session.commit()
