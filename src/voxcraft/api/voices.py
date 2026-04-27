"""/api/tts/voices/* —— 用户自管音色（VoiceRef）的非任务式 CRUD。

「声纹克隆」走 Job 流：上传参考音 + 文字，跑 cloning Provider 合成 + 落 voice_ref。
本模块提供另一条**轻量**路径：只持久化参考音频 + 落 voice_ref，**不调任何 cloning Provider**。
适用于"我已经有声音样本，想加入音色库供后续 TTS 任务复用"的场景。

VoxCPM / IndexTTS 这类 zero-shot 模型本身无状态——能用 voice_id 反查到
reference WAV 即可，无需在创建阶段调用模型。

抽取时会**自动用默认 ASR Provider 转写参考音频**，把 (text, language) 写入
audio_transcripts 缓存供 GPT-SoVITS / VoxCPM 1.x 等需要参考转写的 Provider 复用。
ASR Provider 未配置或失败时仍允许 voice 创建——只是后续合成需要转写的 Provider 会
fail-fast 报清楚的错。这条设计的取舍：voice 抽象（音色 = 录音 + 说话人）保持纯净，
"参考音频说了什么"是模型实现细节而非 voice 元数据，因此独立缓存表持有。
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from voxcraft.api.business import (
    _outputs_dir,
    _select_provider,
    _uploads_dir,
    run_job,
)
from voxcraft.api.schemas.tts import VoiceExtractResponse
from voxcraft.db.engine import get_engine
from voxcraft.db.models import AudioTranscript, Job, Provider, VoiceRef
from voxcraft.errors import InvalidMediaError, ValidationError, VoxCraftError
from voxcraft.video.ffmpeg_io import MediaDecodeError, extract_audio, probe


log = structlog.get_logger()

router = APIRouter(prefix="/tts/voices", tags=["tts"])

# 与 CloningDrawer 一致的纯音频白名单 + 视频白名单（视频走 ffmpeg 抽音轨）
_AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac"}
_VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".webm", ".avi"}

# 转写预览长度上限——前端 ExtractVoiceDrawer 完成提示用，避免长篇大论塞进 Toast
_TRANSCRIPT_PREVIEW_LIMIT = 200


def get_session():
    with Session(get_engine()) as s:
        yield s


def _ext_of(filename: str | None) -> str:
    return Path(filename or "").suffix.lower()


async def _auto_transcribe(
    session: Session,
    request: Request,
    audio_path: Path,
) -> tuple[str | None, str | None, str | None, str | None]:
    """在抽取声纹流程里同步跑一次 ASR，把转写落 audio_transcripts 缓存。

    返回 (text, language, asr_provider_name, warning)：
    - text/language/asr_provider_name 任一为 None 表示未成功落缓存
    - warning：呈现给前端的告警文案（未配置 ASR / ASR 失败 / 转写为空），
      None = 一切正常

    这里直接复用主业务的 run_job 协程：建一行 kind=asr 的 Job → 走 scheduler
    （inproc / pool 都行，LRU=1 可与后续合成共享） → 同步 await 完成。
    比起在 API 进程内直接跑 Whisper：好处是共用模型实例 + 依赖（is_half / device）
    不重复拍板；坏处是会出现一行短期占位的 ASR Job，目前不过滤——抽取声纹是
    低频操作，正常工作流也会偶发 ASR Job，对队列噪声忍受得了。
    """
    asr_row = session.exec(
        select(Provider).where(
            Provider.kind == "asr",
            Provider.enabled == True,  # noqa: E712
            Provider.is_default == True,  # noqa: E712
        )
    ).first()
    if asr_row is None:
        return None, None, None, (
            "未配置默认 ASR Provider，跳过自动转写。"
            "GPT-SoVITS / VoxCPM 1.x 等需要参考转写的合成器无法使用此音色——"
            "请先去「模型管理」配置一个 ASR Provider，然后删除并重抽这个音色。"
        )

    job_id = str(uuid.uuid4())
    session.add(
        Job(
            id=job_id,
            kind="asr",
            status="pending",
            provider_name=asr_row.name,
            request={
                "source_filename": audio_path.name,
                "source_size_bytes": audio_path.stat().st_size,
                # 标记内部任务：未来如果给 UI 加"隐藏内部任务"过滤可按此 key
                "internal_purpose": "voice_extract_transcribe",
            },
            source_path=str(audio_path),
            progress=0.0,
        )
    )
    session.commit()

    try:
        # run_job 在内部 commit 状态变化；返回时 Job 已是 succeeded / failed
        await run_job(job_id, request.app.state)
    except BaseException as e:  # noqa: BLE001
        log.warning("voice.extract.transcribe_run_failed", job=job_id, error=str(e))
        return None, None, None, (
            f"参考音频自动转写失败（ASR 调度异常：{e}）；"
            "音色已保存但需要参考转写的合成器将无法使用此音色。"
        )

    asr_job = session.get(Job, job_id)
    session.refresh(asr_job)
    if asr_job is None or asr_job.status != "succeeded" or not asr_job.result:
        msg = (asr_job.error_message if asr_job else None) or "未知原因"
        return None, None, None, (
            f"参考音频自动转写失败（{msg}）；"
            "音色已保存，需要参考转写的合成器将无法使用此音色。"
        )

    segments = asr_job.result.get("segments") or []
    transcript = " ".join((s.get("text") or "").strip() for s in segments).strip()
    language = asr_job.result.get("language")
    if not transcript:
        return None, None, None, (
            "参考音频转写为空（可能是静音 / 噪声 / 时长过短）。"
            "请用更清晰的录音重新抽取。"
        )

    # 缓存落库：上层调用方所在 session 与 engine 是同一个，直接 add+commit
    session.merge(
        AudioTranscript(
            audio_path=str(audio_path),
            text=transcript,
            language=language,
            asr_provider=asr_row.name,
        )
    )
    session.commit()
    return transcript, language, asr_row.name, None


@router.post("/extract", response_model=VoiceExtractResponse, status_code=201)
async def extract_voice(
    request: Request,
    reference: UploadFile = File(..., description="音频或视频文件；视频会先抽音轨"),
    speaker_name: str | None = Form(None, max_length=128),
    provider: str | None = Form(
        None,
        description="cloning Provider 名；不传走 cloning kind 默认 Provider",
    ),
    start_seconds: float | None = Form(
        None, ge=0,
        description="可选：从原始音频的第几秒开始截取声纹片段（默认从 0 开始）",
    ),
    duration_seconds: float | None = Form(
        None, gt=0,
        description="可选：截取片段时长（秒）。建议 3-10 秒以匹配 GPT-SoVITS 推理约束；"
        "不传则保留整段音轨",
    ),
    session: Session = Depends(get_session),
) -> VoiceExtractResponse:
    ext = _ext_of(reference.filename)
    if ext not in _AUDIO_EXTS and ext not in _VIDEO_EXTS:
        raise InvalidMediaError(
            f"unsupported reference media: {ext or '(none)'}",
            details={
                "filename": reference.filename,
                "supported_audio": sorted(_AUDIO_EXTS),
                "supported_video": sorted(_VIDEO_EXTS),
            },
        )

    # 必须存在一个 cloning Provider 作为归属（即便不调用它，也用于后续 TTS 路由匹配）
    p_row = _select_provider(session, kind="cloning", name=provider)

    voice_id = "vx_" + uuid.uuid4().hex[:12]

    # 1. 临时落地上传文件（uploads/）—— UploadFile.read() 是 async；
    # 大文件 IO 也通过 to_thread 写盘，避免阻塞 event loop
    tmp_path = _uploads_dir() / f"{voice_id}{ext}"
    upload_bytes = await reference.read()
    await asyncio.to_thread(tmp_path.write_bytes, upload_bytes)

    # 2. ffmpeg 抽音轨/标准化；音频统一转 16kHz mono WAV
    voices_dir = _outputs_dir() / "voices"
    voices_dir.mkdir(parents=True, exist_ok=True)
    ref_final = voices_dir / f"{voice_id}.wav"
    duration: float | None = None
    try:
        await asyncio.to_thread(
            extract_audio,
            tmp_path,
            ref_final,
            start_seconds=start_seconds,
            duration_seconds=duration_seconds,
        )
        try:
            info = await asyncio.to_thread(probe, ref_final)
            duration = info.duration
        except MediaDecodeError:
            duration = None
    except MediaDecodeError as e:
        await asyncio.to_thread(lambda: ref_final.unlink(missing_ok=True))
        await asyncio.to_thread(lambda: tmp_path.unlink(missing_ok=True))
        raise VoxCraftError(
            f"failed to extract audio: {e}",
            code="MEDIA_DECODE_ERROR",
            status_code=422,
        ) from e
    finally:
        await asyncio.to_thread(lambda: tmp_path.unlink(missing_ok=True))

    # 3. 写 voice_refs（纯音色——参考音频路径 + speaker_name + 归属 Provider，
    # 不再持有"参考音频说了什么"这种模型实现细节）
    session.add(
        VoiceRef(
            id=voice_id,
            speaker_name=speaker_name,
            reference_audio_path=str(ref_final),
            provider_name=p_row.name,
        )
    )
    session.commit()

    # 4. 同步跑 ASR 把转写写到 audio_transcripts 缓存。失败/未配置时仍允许 voice
    # 创建——但响应里给前端 warning，让用户决定是否补 ASR Provider
    transcript, language, _asr_name, warning = await _auto_transcribe(
        session, request, ref_final,
    )

    transcript_preview: str | None = None
    if transcript:
        transcript_preview = (
            transcript if len(transcript) <= _TRANSCRIPT_PREVIEW_LIMIT
            else transcript[:_TRANSCRIPT_PREVIEW_LIMIT] + "…"
        )

    return VoiceExtractResponse(
        voice_id=voice_id,
        speaker_name=speaker_name,
        provider_name=p_row.name,
        reference_audio_path=str(ref_final),
        duration_seconds=duration,
        transcribed=transcript is not None,
        transcript_preview=transcript_preview,
        transcript_language=language,
        transcribe_warning=warning,
    )


@router.get("/{voice_id}/sample")
def get_voice_sample(
    voice_id: str,
    session: Session = Depends(get_session),
):
    """流式返回 cloned voice 的参考音频文件，供前端 <audio> 试听。

    仅 vx_ 前缀的 cloned voice 有此能力；preset 音色（id=Provider 名）由 Provider
    端自管样本，本端点对 preset 返回 404。
    """
    if not voice_id.startswith("vx_"):
        raise VoxCraftError(
            "preset voices have no sample bound to voice_refs",
            code="VOICE_NOT_FOUND",
            status_code=404,
        )
    row = session.get(VoiceRef, voice_id)
    if row is None or not row.reference_audio_path:
        raise VoxCraftError(
            f"voice not found: {voice_id}",
            code="VOICE_NOT_FOUND",
            status_code=404,
        )
    p = Path(row.reference_audio_path)
    if not p.is_file():
        raise VoxCraftError(
            f"reference audio missing on disk for {voice_id}",
            code="VOICE_SAMPLE_MISSING",
            status_code=410,
        )
    media_type = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg",
        ".m4a": "audio/mp4",
        ".flac": "audio/flac",
        ".aac": "audio/aac",
    }.get(p.suffix.lower(), "application/octet-stream")
    return FileResponse(p, media_type=media_type, filename=p.name)


@router.delete("/{voice_id}", status_code=204)
def delete_voice(
    voice_id: str,
    session: Session = Depends(get_session),
):
    """删除音色：DB row + 磁盘文件 + audio_transcripts 缓存行。"""
    row = session.get(VoiceRef, voice_id)
    if row is None:
        raise VoxCraftError(
            f"voice not found: {voice_id}",
            code="VOICE_NOT_FOUND",
            status_code=404,
        )
    if not voice_id.startswith("vx_"):
        # preset 类型音色（id=Provider 名）由 Provider 配置管理，不在此端点删除
        raise ValidationError(
            "preset voices are managed via providers, not deletable here",
            details={"voice_id": voice_id},
        )
    audio_path = row.reference_audio_path
    if audio_path:
        Path(audio_path).unlink(missing_ok=True)
        # 级联清缓存——同一段音频不会再有别的 voice 复用（VoxCraft 的 ref_final
        # 路径包含 voice_id 唯一前缀），删了不会影响别的 voice
        cached = session.get(AudioTranscript, audio_path)
        if cached is not None:
            session.delete(cached)
    session.delete(row)
    session.commit()
    return None
