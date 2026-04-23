"""OpenAI 兼容 API 层（ADR-012）。

对内复用 business.run_job 异步 runner；对外呈现 HTTP 同步 + OpenAI schema。

端点：
- POST /v1/audio/transcriptions   对齐 OpenAI Whisper
- POST /v1/audio/speech           对齐 OpenAI TTS
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from sqlmodel import Session

from voxcraft.api import business
from voxcraft.api.schemas.oai import (
    OaiErrorBody,
    OaiErrorEnvelope,
    OaiSpeechRequest,
    OaiTranscriptionSegment,
    OaiTranscriptionVerbose,
    SpeechFormat,
    TranscriptionFormat,
)
from voxcraft.db.engine import get_engine
from voxcraft.db.models import Job
from voxcraft.errors import ValidationError, VoxCraftError


router = APIRouter(prefix="/v1/audio", tags=["openai-compat"])


def get_session():
    with Session(get_engine()) as s:
        yield s


# ---------- 内部 helpers ----------

_POLL_INTERVAL_S = 0.1
_DEFAULT_TIMEOUT_S = 600.0
_TERMINAL = {"succeeded", "failed", "cancelled"}


async def _wait_for_job(job_id: str, timeout: float = _DEFAULT_TIMEOUT_S) -> Job:
    """主进程协程：轮询 DB 直到 Job 进入终态。不占锁，仅读。"""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        with Session(get_engine()) as session:
            job = session.get(Job, job_id)
            if job is None:
                raise VoxCraftError(
                    f"Job disappeared mid-wait: {job_id}",
                    code="JOB_NOT_FOUND",
                    status_code=500,
                )
            if job.status in _TERMINAL:
                return job
        if asyncio.get_event_loop().time() >= deadline:
            raise VoxCraftError(
                "Request timed out; job continues in background",
                code="TIMEOUT",
                status_code=504,
                details={"job_id": job_id},
            )
        await asyncio.sleep(_POLL_INTERVAL_S)


def _oai_error_response(exc: BaseException, fallback_status: int = 500) -> JSONResponse:
    """VoxCraft 异常 → OpenAI error envelope。"""
    if isinstance(exc, VoxCraftError):
        code = exc.code
        message = exc.message
        status = exc.status_code
    else:
        code = "INTERNAL_ERROR"
        message = str(exc) or exc.__class__.__name__
        status = fallback_status

    if status == 400:
        oai_type = "invalid_request_error"
    elif status == 404:
        oai_type = "not_found_error"
    elif 400 <= status < 500:
        oai_type = "invalid_request_error"
    else:
        oai_type = "server_error"

    env = OaiErrorEnvelope(error=OaiErrorBody(message=message, type=oai_type, code=code))
    return JSONResponse(status_code=status, content=env.model_dump())


def _resolve_provider_name(requested_model: str, kind: str) -> str | None:
    """OpenAI `model` 字段 → VoxCraft provider name。

    - 以 `whisper-`/`tts-`/`openai-` 等泛名开头 → 返回 None（走默认）
    - 其他视作具体 provider name
    """
    m = (requested_model or "").strip().lower()
    if not m or m in {"whisper-1", "whisper", "tts-1", "tts-1-hd"}:
        return None
    generic_prefixes = ("whisper-", "tts-")
    if m.startswith(generic_prefixes):
        return None
    return requested_model


# ---------- SRT / VTT 序列化 ----------

def _fmt_ts(t: float, comma: bool = True) -> str:
    """秒 → HH:MM:SS,mmm（SRT）或 HH:MM:SS.mmm（VTT）。"""
    if t < 0:
        t = 0.0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    sep = "," if comma else "."
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def _segments_to_srt(segments: list[dict]) -> str:
    blocks: list[str] = []
    for i, seg in enumerate(segments, start=1):
        blocks.append(
            f"{i}\n{_fmt_ts(seg['start'])} --> {_fmt_ts(seg['end'])}\n{seg['text'].strip()}\n"
        )
    return "\n".join(blocks)


def _segments_to_vtt(segments: list[dict]) -> str:
    lines = ["WEBVTT", ""]
    for seg in segments:
        lines.append(
            f"{_fmt_ts(seg['start'], comma=False)} --> {_fmt_ts(seg['end'], comma=False)}"
        )
        lines.append(seg["text"].strip())
        lines.append("")
    return "\n".join(lines)


# ---------- /v1/audio/transcriptions ----------

@router.post("/transcriptions")
async def transcriptions(
    request: Request,
    file: UploadFile = File(...),
    model: str = Form("whisper-1"),
    language: str | None = Form(None),
    response_format: TranscriptionFormat = Form("json"),
    temperature: float | None = Form(None),  # noqa: ARG001 — 当前忽略
    prompt: str | None = Form(None),  # noqa: ARG001
    session: Session = Depends(get_session),
):
    try:
        provider_name = _resolve_provider_name(model, kind="asr")
        p_row = business._select_provider(session, kind="asr", name=provider_name)
        job_id = str(uuid.uuid4())
        source_path = business._save_upload(file, job_id, ".wav")
        now = datetime.now(UTC)

        session.add(
            Job(
                id=job_id, kind="asr", status="pending",
                provider_name=p_row.name,
                request={
                    "source_filename": file.filename,
                    "language": language,
                    "oai_model": model,
                },
                source_path=str(source_path),
                progress=0.0, created_at=now,
            )
        )
        session.commit()
        await business._publish_status(
            request.app.state.event_bus, job_id=job_id, kind="asr", status="pending",
        )
        asyncio.create_task(business.run_job(job_id, request.app.state))

        job = await _wait_for_job(job_id)
    except VoxCraftError as e:
        return _oai_error_response(e)
    except BaseException as e:  # noqa: BLE001
        return _oai_error_response(e)

    if job.status != "succeeded":
        err = VoxCraftError(
            job.error_message or "Transcription failed",
            code=job.error_code or "INFERENCE_ERROR",
            status_code=500,
            details={"job_id": job.id},
        )
        resp = _oai_error_response(err)
        resp.headers["X-VoxCraft-Job-Id"] = job.id
        return resp

    result = job.result or {}
    segments = result.get("segments") or []
    full_text = " ".join(s.get("text", "").strip() for s in segments).strip()
    language_out = result.get("language", "")
    duration = float(result.get("duration") or 0.0)
    headers = {"X-VoxCraft-Job-Id": job.id}

    if response_format == "json":
        return JSONResponse(content={"text": full_text}, headers=headers)
    if response_format == "text":
        return PlainTextResponse(content=full_text, headers=headers)
    if response_format == "srt":
        return PlainTextResponse(content=_segments_to_srt(segments), headers=headers)
    if response_format == "vtt":
        return PlainTextResponse(
            content=_segments_to_vtt(segments),
            headers=headers,
            media_type="text/vtt",
        )
    # verbose_json
    body = OaiTranscriptionVerbose(
        language=language_out,
        duration=duration,
        text=full_text,
        segments=[
            OaiTranscriptionSegment(
                id=i,
                start=float(s.get("start") or 0.0),
                end=float(s.get("end") or 0.0),
                text=s.get("text", ""),
            )
            for i, s in enumerate(segments)
        ],
    )
    return JSONResponse(content=body.model_dump(), headers=headers)


# ---------- /v1/audio/speech ----------

_OAI_FORMAT_TO_VC: dict[SpeechFormat, Literal["wav", "mp3", "ogg"]] = {
    "wav": "wav", "mp3": "mp3",
    # OpenAI 专有格式退化到最近可得：Piper 原生只出 wav
    "opus": "ogg", "flac": "wav", "aac": "mp3", "pcm": "wav",
}
_FORMAT_MEDIA_TYPE: dict[SpeechFormat, str] = {
    "mp3": "audio/mpeg",
    "opus": "audio/ogg",
    "aac": "audio/aac",
    "flac": "audio/flac",
    "wav": "audio/wav",
    "pcm": "audio/L16",
}


@router.post("/speech")
async def speech(
    request: Request,
    body: OaiSpeechRequest,
    session: Session = Depends(get_session),
):
    try:
        if not body.input.strip():
            raise ValidationError(
                "input must be a non-empty string",
                details={"field": "input"},
            )
        provider_name = _resolve_provider_name(body.model, kind="tts")
        p_row = business._select_provider(session, kind="tts", name=provider_name)
        job_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        vc_format = _OAI_FORMAT_TO_VC[body.response_format]

        session.add(
            Job(
                id=job_id, kind="tts", status="pending",
                provider_name=p_row.name,
                request={
                    "text": body.input,
                    "voice_id": body.voice,
                    "speed": body.speed,
                    "format": vc_format,
                    "oai_model": body.model,
                    "oai_response_format": body.response_format,
                },
                progress=0.0, created_at=now,
            )
        )
        session.commit()
        await business._publish_status(
            request.app.state.event_bus, job_id=job_id, kind="tts", status="pending",
        )
        asyncio.create_task(business.run_job(job_id, request.app.state))

        job = await _wait_for_job(job_id)
    except ValidationError as e:
        return _oai_error_response(e)
    except VoxCraftError as e:
        return _oai_error_response(e)
    except BaseException as e:  # noqa: BLE001
        return _oai_error_response(e)

    headers = {"X-VoxCraft-Job-Id": job.id}
    if job.status != "succeeded":
        err = VoxCraftError(
            job.error_message or "Speech synthesis failed",
            code=job.error_code or "INFERENCE_ERROR",
            status_code=500,
            details={"job_id": job.id},
        )
        resp = _oai_error_response(err)
        resp.headers.update(headers)
        return resp

    output_path = job.output_path
    if not output_path or not Path(output_path).exists():
        err = VoxCraftError("Output missing", code="JOB_OUTPUT_MISSING", status_code=500)
        resp = _oai_error_response(err)
        resp.headers.update(headers)
        return resp

    audio_bytes = Path(output_path).read_bytes()
    return Response(
        content=audio_bytes,
        media_type=_FORMAT_MEDIA_TYPE[body.response_format],
        headers=headers,
    )
