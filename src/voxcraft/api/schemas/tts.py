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
    provider_name: str                    # 归属 Provider；前端按此过滤
    # cloning 整体下线后只剩 preset，但保留字段是为了让前端代码不必判 undefined
    source: Literal["preset"] = "preset"


class VoicesResponse(BaseModel):
    voices: list[VoiceSchema]
