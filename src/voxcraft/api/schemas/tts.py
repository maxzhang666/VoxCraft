"""TTS 请求/响应 schemas。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TtsRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    voice_id: str
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    format: Literal["wav", "mp3", "ogg"] = "wav"
    provider: str | None = None


class VoiceSchema(BaseModel):
    id: str
    language: str
    gender: str | None = None
    sample_url: str | None = None
    provider_name: str                    # 归属 Provider；前端按此过滤
    source: Literal["preset", "cloned"]   # preset=Provider 内置单音色；cloned=VoiceRef


class VoicesResponse(BaseModel):
    voices: list[VoiceSchema]


class VoiceExtractResponse(BaseModel):
    """POST /api/tts/voices/extract 返回：抽取声纹后的 voice 信息。"""

    voice_id: str
    speaker_name: str | None = None
    provider_name: str
    reference_audio_path: str
    duration_seconds: float | None = None
