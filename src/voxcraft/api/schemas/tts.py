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


class VoicesResponse(BaseModel):
    voices: list[VoiceSchema]
