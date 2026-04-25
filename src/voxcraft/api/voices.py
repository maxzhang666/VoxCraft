"""/api/tts/voices/* —— 用户自管音色（VoiceRef）的非任务式 CRUD。

「声纹克隆」走 Job 流：上传参考音 + 文字，跑 cloning Provider 合成 + 落 voice_ref。
本模块提供另一条**轻量**路径：只持久化参考音频 + 落 voice_ref，**不调任何 Provider**。
适用于"我已经有声音样本，想加入音色库供后续 TTS 任务复用"的场景。

VoxCPM / IndexTTS 这类 zero-shot 模型本身无状态——能用 voice_id 反查到
reference WAV 即可，无需在创建阶段调用模型。
"""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlmodel import Session

from voxcraft.api.business import _outputs_dir, _select_provider, _uploads_dir
from voxcraft.api.schemas.tts import VoiceExtractResponse
from voxcraft.db.engine import get_engine
from voxcraft.db.models import VoiceRef
from voxcraft.errors import InvalidMediaError, ValidationError, VoxCraftError
from voxcraft.video.ffmpeg_io import MediaDecodeError, extract_audio, probe


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

    # 1. 临时落地上传文件（uploads/）
    tmp_path = _uploads_dir() / f"{voice_id}{ext}"
    tmp_path.write_bytes(reference.file.read())

    # 2. 视频 → ffmpeg 抽音轨；音频 → 直接复制为 .wav 占位（便于后续统一处理）
    voices_dir = _outputs_dir() / "voices"
    voices_dir.mkdir(parents=True, exist_ok=True)
    ref_final = voices_dir / f"{voice_id}.wav"
    duration: float | None = None
    try:
        if ext in _VIDEO_EXTS:
            extract_audio(tmp_path, ref_final)
        else:
            # 已是音频：用 ffmpeg 标准化到 16kHz mono WAV，统一下游 Provider 期望
            extract_audio(tmp_path, ref_final)
        # 探测时长用作展示
        try:
            info = probe(ref_final)
            duration = info.duration
        except MediaDecodeError:
            duration = None
    except MediaDecodeError as e:
        # 抽音失败：清理半成品
        ref_final.unlink(missing_ok=True)
        tmp_path.unlink(missing_ok=True)
        raise VoxCraftError(
            f"failed to extract audio: {e}",
            code="MEDIA_DECODE_ERROR",
            status_code=422,
        ) from e
    finally:
        tmp_path.unlink(missing_ok=True)

    # 3. 写 voice_refs
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


@router.delete("/{voice_id}", status_code=204)
def delete_voice(
    voice_id: str,
    session: Session = Depends(get_session),
):
    """删除音色：DB row + 磁盘文件。"""
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
    if row.reference_audio_path:
        Path(row.reference_audio_path).unlink(missing_ok=True)
    session.delete(row)
    session.commit()
    return None
