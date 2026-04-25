"""视频语音级翻译编排端点（ADR-014 / v0.4.0）。

HTTP 提交 + 14 条前置验证 + 写 Job(pending) + 派发 run_job 后台任务。
真正的 ASR → 翻译 → TTS → mux 由 `voxcraft.video.orchestrator.run_video_translate`
在 scheduler 中执行。

设计原则：
- 参数化 + 前置验证 > 业务默认硬编码（用户讨论结论）
- 验证失败一律 422，不入队；节省队列时间
- Provider 能力（CAPABILITIES）声明驱动克隆支持性校验
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlmodel import Session, select

from voxcraft.api.business import (
    _outputs_dir,
    _publish_status,
    _uploads_dir,
    get_session,
    run_job,
)
from voxcraft.api.schemas.job import JobSubmitResponse
from voxcraft.api.schemas.video_translate import (
    DEFAULT_TRANSLATE_MAX_INFLATION,
    MAX_SPEEDUP,
    MAX_SYSTEM_PROMPT_LEN,
    MAX_TRANSLATE_MAX_INFLATION,
    MIN_SPEEDUP,
    MIN_TRANSLATE_MAX_INFLATION,
    SUPPORTED_EXTENSIONS,
    VIDEO_EXTENSIONS,
    AlignMode,
    SubtitleMode,
    is_valid_lang,
)
from voxcraft.config import get_settings
from voxcraft.db.models import Job, LlmProvider, Provider
from voxcraft.runtime.scheduler_api import JobRequest
from voxcraft.errors import (
    CloneNotSupportedDefaultError,
    CloneNotSupportedError,
    InvalidLangError,
    InvalidMediaError,
    LlmNotConfiguredError,
    UploadTooLargeError,
    ValidationError,
)
from voxcraft.providers import capabilities
from voxcraft.providers.registry import resolve


log = structlog.get_logger()
router = APIRouter(tags=["video-translate"])


# ---------- 前置验证 helpers ----------

def _ext_of(filename: str | None) -> str:
    if not filename:
        return ""
    return Path(filename).suffix.lower()


def _check_content_length(request: Request, limit: int) -> None:
    """在读取完整上传体之前做一层 Content-Length 预检。"""
    raw = request.headers.get("content-length")
    if raw is None:
        return
    try:
        size = int(raw)
    except ValueError:
        return
    if size > limit:
        raise UploadTooLargeError(
            f"Content-Length {size} exceeds limit {limit}",
            details={"limit": limit, "got": size},
        )


def _validate_provider_row(
    session: Session,
    *,
    provider_id: int,
    expected_kind: str,
    role: str,
) -> Provider:
    """按 id 取 Provider 记录并校验 kind + enabled。"""
    row = session.get(Provider, provider_id)
    if row is None:
        raise ValidationError(
            f"{role} provider not found: id={provider_id}",
            code="PROVIDER_NOT_FOUND",
            status_code=422,
            details={"provider_id": provider_id, "role": role},
        )
    if not row.enabled:
        raise ValidationError(
            f"{role} provider is disabled: {row.name}",
            code="PROVIDER_NOT_FOUND",
            status_code=422,
            details={"provider_id": provider_id, "role": role},
        )
    if row.kind != expected_kind:
        raise ValidationError(
            f"{role} provider kind mismatch: expected {expected_kind}, got {row.kind}",
            code="PROVIDER_NOT_FOUND",
            status_code=422,
            details={
                "provider_id": provider_id,
                "role": role,
                "expected_kind": expected_kind,
                "actual_kind": row.kind,
            },
        )
    return row


def _provider_capabilities(class_name: str) -> frozenset[str]:
    return resolve(class_name).CAPABILITIES


def _default_provider(session: Session, kind: str) -> Provider | None:
    return session.exec(
        select(Provider).where(
            Provider.kind == kind,
            Provider.enabled == True,  # noqa: E712
            Provider.is_default == True,  # noqa: E712
        )
    ).first()


def _list_clone_capable_tts_ids(session: Session) -> list[int]:
    """枚举所有 enabled + 支持 clone 的 TTS/cloning Provider id，用于错误消息引导。"""
    rows = session.exec(
        select(Provider).where(
            Provider.enabled == True,  # noqa: E712
            Provider.kind.in_(["tts", "cloning"]),  # type: ignore[attr-defined]
        )
    ).all()
    return [
        row.id for row in rows
        if row.id is not None
        and capabilities.CLONE in _provider_capabilities(row.class_name)
    ]


# ---------- 路由 ----------

@router.post("/video-translate", response_model=JobSubmitResponse, status_code=202)
async def submit_video_translate(
    request: Request,
    source_file: UploadFile = File(...),
    target_lang: str = Form(..., min_length=1, max_length=16),
    source_lang: str | None = Form(None, max_length=16),
    subtitle_mode: SubtitleMode = Form(SubtitleMode.soft),
    clone_voice: bool = Form(True),
    align_mode: AlignMode = Form(AlignMode.elastic),
    align_max_speedup: float = Form(1.3, ge=MIN_SPEEDUP, le=MAX_SPEEDUP),
    asr_provider_id: int | None = Form(None),
    tts_provider_id: int | None = Form(None),
    llm_provider_id: int | None = Form(None),
    system_prompt: str | None = Form(None, max_length=MAX_SYSTEM_PROMPT_LEN),
    translate_max_inflation: float = Form(
        DEFAULT_TRANSLATE_MAX_INFLATION,
        ge=MIN_TRANSLATE_MAX_INFLATION, le=MAX_TRANSLATE_MAX_INFLATION,
    ),
    # ---- ASR 调优透传（与 /api/asr 同语义，缺省走 Whisper Provider config）----
    asr_initial_prompt: str | None = Form(None),
    asr_temperature: float | None = Form(None),
    asr_beam_size: int | None = Form(None),
    asr_vad_filter: bool | None = Form(None),
    asr_condition_on_previous_text: bool | None = Form(None),
    asr_word_timestamps: bool | None = Form(None),
    session: Session = Depends(get_session),
) -> JobSubmitResponse:
    settings = get_settings()

    # 1. 上传大小（Content-Length 预检）
    _check_content_length(request, settings.max_upload_size)

    # 2. 文件类型（扩展名白名单）
    ext = _ext_of(source_file.filename)
    if ext not in SUPPORTED_EXTENSIONS:
        raise InvalidMediaError(
            f"unsupported media extension: {ext or '(none)'}",
            details={
                "filename": source_file.filename,
                "supported": sorted(SUPPORTED_EXTENSIONS),
            },
        )
    is_video_input = ext in VIDEO_EXTENSIONS

    # 3. 语言格式
    if not is_valid_lang(target_lang):
        raise InvalidLangError(
            f"invalid target_lang: {target_lang}",
            details={"field": "target_lang", "got": target_lang},
        )
    if source_lang is not None and not is_valid_lang(source_lang):
        raise InvalidLangError(
            f"invalid source_lang: {source_lang}",
            details={"field": "source_lang", "got": source_lang},
        )

    # 4. 系统 prompt 规范化（空白串等价于 null）
    sp = system_prompt.strip() if system_prompt else None
    if sp == "":
        sp = None

    # 5. Provider 存在性 + kind 匹配
    if asr_provider_id is not None:
        _validate_provider_row(
            session, provider_id=asr_provider_id, expected_kind="asr", role="asr",
        )
    if tts_provider_id is not None:
        tts_row = session.get(Provider, tts_provider_id)
        if tts_row is None or not tts_row.enabled:
            raise ValidationError(
                f"tts provider not found: id={tts_provider_id}",
                code="PROVIDER_NOT_FOUND",
                status_code=422,
                details={"provider_id": tts_provider_id, "role": "tts"},
            )
        if tts_row.kind not in ("tts", "cloning"):
            raise ValidationError(
                f"tts provider kind mismatch: got {tts_row.kind}",
                code="PROVIDER_NOT_FOUND",
                status_code=422,
                details={
                    "provider_id": tts_provider_id,
                    "expected_kind": "tts|cloning",
                    "actual_kind": tts_row.kind,
                },
            )
    else:
        tts_row = None

    # 6. 克隆能力：显式指定 → 该 Provider 必须声明 "clone"
    if clone_voice and tts_row is not None:
        caps = _provider_capabilities(tts_row.class_name)
        if capabilities.CLONE not in caps:
            raise CloneNotSupportedError(
                f"provider {tts_row.name} does not support voice cloning",
                details={
                    "provider_id": tts_row.id,
                    "class_name": tts_row.class_name,
                    "capabilities": sorted(caps),
                },
            )

    # 7. 克隆能力：未指定 tts_provider_id → 查默认 Provider 是否支持 clone
    #    clone_voice=true 时优先选 cloning kind（生来支持克隆）；否则 tts kind
    if clone_voice and tts_row is None:
        default_tts = _default_provider(session, "cloning") or _default_provider(
            session, "tts",
        )
        if default_tts is None:
            raise ValidationError(
                "no default tts/cloning provider configured",
                code="PROVIDER_NOT_FOUND", status_code=422,
                details={"role": "tts"},
            )
        caps = _provider_capabilities(default_tts.class_name)
        if capabilities.CLONE not in caps:
            clone_candidates = _list_clone_capable_tts_ids(session)
            raise CloneNotSupportedDefaultError(
                f"default tts provider {default_tts.name} does not support cloning; "
                f"please specify tts_provider_id explicitly",
                details={
                    "default_provider_id": default_tts.id,
                    "default_class": default_tts.class_name,
                    "clone_capable_provider_ids": clone_candidates,
                },
            )

    # 8. LLM 可用性
    if llm_provider_id is not None:
        llm_row = session.get(LlmProvider, llm_provider_id)
        if llm_row is None or not llm_row.enabled:
            raise ValidationError(
                f"llm provider not found: id={llm_provider_id}",
                code="PROVIDER_NOT_FOUND",
                status_code=422,
                details={"provider_id": llm_provider_id, "role": "llm"},
            )
    else:
        default_llm = session.exec(
            select(LlmProvider).where(
                LlmProvider.enabled == True,  # noqa: E712
                LlmProvider.is_default == True,  # noqa: E712
            )
        ).first()
        if default_llm is None:
            raise LlmNotConfiguredError(
                "no default LLM provider configured; "
                "add one at /admin/llm or pass llm_provider_id",
            )

    # ---------- 所有验证通过，落盘 + 写 Job ----------

    job_id = str(uuid.uuid4())
    source_path, source_size = _save_upload_with_size_check(
        source_file, job_id, ext, settings.max_upload_size,
    )

    # ASR / TTS Provider 名（优先显式，否则留空；阶段 3 由 orchestrator 选默认）
    asr_name: str | None = None
    tts_name: str | None = None
    if asr_provider_id is not None:
        asr_name = session.get(Provider, asr_provider_id).name  # type: ignore[union-attr]
    if tts_provider_id is not None:
        tts_name = session.get(Provider, tts_provider_id).name  # type: ignore[union-attr]

    # 收集非空 ASR 调优字段；空值走 Whisper Provider 默认值
    asr_options: dict = {}
    if asr_initial_prompt is not None:
        asr_options["initial_prompt"] = asr_initial_prompt
    for k, v in (
        ("temperature", asr_temperature),
        ("beam_size", asr_beam_size),
        ("vad_filter", asr_vad_filter),
        ("condition_on_previous_text", asr_condition_on_previous_text),
        ("word_timestamps", asr_word_timestamps),
    ):
        if v is not None:
            asr_options[k] = v

    request_meta: dict = {
        "source_filename": source_file.filename,
        "source_size_bytes": source_size,
        "source_is_video": is_video_input,
        "target_lang": target_lang,
        "source_lang": source_lang,
        "subtitle_mode": subtitle_mode.value,
        "clone_voice": clone_voice,
        "align_mode": align_mode.value,
        "align_max_speedup": align_max_speedup,
        "asr_provider_id": asr_provider_id,
        "tts_provider_id": tts_provider_id,
        "llm_provider_id": llm_provider_id,
        "system_prompt": sp,
        "translate_max_inflation": translate_max_inflation,
        "asr_provider_name": asr_name,
        "tts_provider_name": tts_name,
        "asr_options": asr_options,
    }

    now = datetime.now(UTC)
    session.add(
        Job(
            id=job_id,
            kind="video_translate",
            status="pending",
            provider_name=None,  # 编排涉及多 Provider，本字段置空
            request=request_meta,
            source_path=str(source_path),
            progress=0.0,
            created_at=now,
        )
    )
    session.commit()

    await _publish_status(
        request.app.state.event_bus,
        job_id=job_id,
        kind="video_translate",
        status="pending",
    )

    log.info(
        "video_translate.submitted",
        job_id=job_id,
        is_video=is_video_input,
        target_lang=target_lang,
    )

    _outputs_dir()

    # 派发后台 runner；run_job 内部识别 kind=video_translate 后走 orchestrator。
    asyncio.create_task(run_job(job_id, request.app.state))

    return JobSubmitResponse(job_id=job_id, status="pending")


# ---------- Orchestrator JobRequest 构造（被 business.run_job 调用） ----------

def build_video_translate_request(
    session: Session, job: Job, output_dir: str,
) -> JobRequest:
    """把 Job 持久化的编排参数 + DB 中的 ASR/TTS/LLM 配置，打包为 JobRequest。

    - Provider id 缺省时走 is_default（clone_voice=true 时优先 cloning kind）
    - 任何查找失败抛 VoxCraftError，由 business.run_job 写失败
    """
    meta = dict(job.request or {})
    clone_voice = bool(meta.get("clone_voice"))

    asr_row = _pick_provider(
        session,
        explicit_id=meta.get("asr_provider_id"),
        kinds=("asr",),
        role="asr",
    )
    tts_row = _pick_tts_provider(
        session,
        explicit_id=meta.get("tts_provider_id"),
        prefer_clone=clone_voice,
    )
    llm_row = _pick_llm(session, explicit_id=meta.get("llm_provider_id"))

    orch_meta = {
        "asr": {
            "class_name": asr_row.class_name,
            "name": asr_row.name,
            "config": dict(asr_row.config or {}),
            "options": dict(meta.get("asr_options") or {}),
        },
        "tts": {
            "class_name": tts_row.class_name,
            "name": tts_row.name,
            "config": dict(tts_row.config or {}),
        },
        "llm": {
            "base_url": llm_row.base_url,
            "api_key": llm_row.api_key,
            "model": llm_row.model,
        },
        "target_lang": meta["target_lang"],
        "source_lang": meta.get("source_lang"),
        "subtitle_mode": meta.get("subtitle_mode", "soft"),
        "clone_voice": clone_voice,
        "align_mode": meta.get("align_mode", "elastic"),
        "align_max_speedup": float(meta.get("align_max_speedup", 1.3)),
        "system_prompt": meta.get("system_prompt"),
        "translate_max_inflation": float(meta.get("translate_max_inflation", 5.0)),
    }

    return JobRequest(
        job_id=job.id,
        kind="video_translate",
        provider_name="video-translate",
        class_name="VideoTranslateOrchestrator",  # 虚名，不在 registry
        provider_config={},
        request_meta=orch_meta,
        source_path=job.source_path,
        output_dir=output_dir,
    )


def _pick_provider(
    session: Session,
    *,
    explicit_id: int | None,
    kinds: tuple[str, ...],
    role: str,
) -> Provider:
    if explicit_id is not None:
        row = session.get(Provider, explicit_id)
        if row is None or not row.enabled or row.kind not in kinds:
            raise ValidationError(
                f"{role} provider not available: id={explicit_id}",
                code="PROVIDER_NOT_FOUND",
                details={"role": role, "provider_id": explicit_id},
            )
        return row
    for kind in kinds:
        row = session.exec(
            select(Provider).where(
                Provider.kind == kind,
                Provider.enabled == True,  # noqa: E712
                Provider.is_default == True,  # noqa: E712
            )
        ).first()
        if row is not None:
            return row
    raise ValidationError(
        f"no default {role} provider configured",
        code="PROVIDER_NOT_FOUND",
        details={"role": role, "kinds": list(kinds)},
    )


def _pick_tts_provider(
    session: Session, *, explicit_id: int | None, prefer_clone: bool,
) -> Provider:
    if explicit_id is not None:
        return _pick_provider(
            session, explicit_id=explicit_id,
            kinds=("tts", "cloning"), role="tts",
        )
    # 未显式：clone_voice 开启时优先从 cloning kind 选默认；否则 tts 优先
    kinds: tuple[str, ...] = (
        ("cloning", "tts") if prefer_clone else ("tts", "cloning")
    )
    return _pick_provider(
        session, explicit_id=None, kinds=kinds, role="tts",
    )


def _pick_llm(session: Session, *, explicit_id: int | None) -> LlmProvider:
    if explicit_id is not None:
        row = session.get(LlmProvider, explicit_id)
        if row is None or not row.enabled:
            raise ValidationError(
                f"llm provider not available: id={explicit_id}",
                code="PROVIDER_NOT_FOUND",
                details={"role": "llm", "provider_id": explicit_id},
            )
        return row
    row = session.exec(
        select(LlmProvider).where(
            LlmProvider.enabled == True,  # noqa: E712
            LlmProvider.is_default == True,  # noqa: E712
        )
    ).first()
    if row is None:
        raise LlmNotConfiguredError("no default LLM provider configured")
    return row


# ---------- 上传 helper：流式写盘 + 大小校验（兜底，防止 Content-Length 缺失） ----------

def _save_upload_with_size_check(
    upload: UploadFile, job_id: str, ext: str, limit: int,
) -> tuple[Path, int]:
    """写盘时逐块累计大小；超限立即删除半成品 + 抛错。

    返回 (dest_path, total_size_bytes)，供调用方写入 Job.request.source_size_bytes。
    """
    dest = _uploads_dir() / f"{job_id}{ext}"
    total = 0
    try:
        with dest.open("wb") as f:
            while True:
                chunk = upload.file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise UploadTooLargeError(
                        f"upload exceeded limit {limit} bytes (streamed)",
                        details={"limit": limit, "streamed_so_far": total},
                    )
                f.write(chunk)
    except UploadTooLargeError:
        if dest.exists():
            try:
                dest.unlink()
            except OSError:
                pass
        raise
    except Exception:
        if dest.exists():
            try:
                dest.unlink()
            except OSError:
                pass
        raise
    return dest, total
