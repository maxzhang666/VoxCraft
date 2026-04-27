"""/api/tts/voices/* —— 用户自管音色（VoiceRef）的非任务式 CRUD。

「声纹克隆」走 Job 流：上传参考音 + 文字，跑 cloning Provider 合成 + 落 voice_ref。
本模块提供另一条**轻量**路径：只持久化参考音频 + 落 voice_ref，**不调任何 Provider**。
适用于"我已经有声音样本，想加入音色库供后续 TTS 任务复用"的场景。

设计原则：voice = 一段音频 + 说话人，**与任何模型 Provider 解耦**。
- 抽取声纹**不**触发 ASR，不依赖 ASR Provider 存在。
- "参考音频里说了什么"是部分 cloning Provider（GPT-SoVITS / VoxCPM 1.x）的实现
  细节，由 worker 在合成时 lazy 跑 ASR 并缓存（见 worker_runners._ensure_audio_transcript）。
- 不需要参考转写的 Provider（Piper 预设、VoxCPM 2 基础克隆）从头到尾用不到 ASR。
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session

from voxcraft.api.business import _outputs_dir, _select_provider, _uploads_dir
from voxcraft.api.schemas.tts import VoiceExtractResponse
from voxcraft.db.engine import get_engine
from voxcraft.db.models import AudioTranscript, VoiceRef
from voxcraft.errors import InvalidMediaError, ValidationError, VoxCraftError
from voxcraft.video.ffmpeg_io import MediaDecodeError, extract_audio, probe


log = structlog.get_logger()

router = APIRouter(prefix="/tts/voices", tags=["tts"])

# 与 CloningDrawer 一致的纯音频白名单 + 视频白名单（视频走 ffmpeg 抽音轨）
_AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac"}
_VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".webm", ".avi"}


def get_session():
    with Session(get_engine()) as s:
        yield s


def _ext_of(filename: str | None) -> str:
    return Path(filename or "").suffix.lower()


@router.post("/extract", response_model=VoiceExtractResponse, status_code=201)
async def extract_voice(
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
    # 与任何模型 Provider 解耦：不跑 ASR、不写 audio_transcripts）
    session.add(
        VoiceRef(
            id=voice_id,
            speaker_name=speaker_name,
            reference_audio_path=str(ref_final),
            provider_name=p_row.name,
        )
    )
    session.commit()

    return VoiceExtractResponse(
        voice_id=voice_id,
        speaker_name=speaker_name,
        provider_name=p_row.name,
        reference_audio_path=str(ref_final),
        duration_seconds=duration,
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
    """删除音色：DB row + 磁盘文件 + audio_transcripts 缓存行（如有）。"""
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
