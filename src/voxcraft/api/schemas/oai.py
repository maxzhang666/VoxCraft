"""OpenAI 兼容 schema（ADR-012）。

对齐 OpenAI Whisper / TTS API 的请求/响应形状，内部字段映射到 VoxCraft 语义。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ---------- /v1/audio/transcriptions ----------

TranscriptionFormat = Literal["json", "text", "srt", "verbose_json", "vtt"]


class OaiTranscriptionWord(BaseModel):
    """timestamp_granularities[]=word 时返回的词级时间戳。"""

    word: str
    start: float
    end: float


class OaiTranscriptionSegment(BaseModel):
    id: int
    start: float
    end: float
    text: str


class OaiTranscriptionJson(BaseModel):
    """response_format=json（默认）。"""

    text: str


class OaiTranscriptionVerbose(BaseModel):
    """response_format=verbose_json。"""

    task: Literal["transcribe"] = "transcribe"
    language: str
    duration: float
    text: str
    segments: list[OaiTranscriptionSegment]
    words: list[OaiTranscriptionWord] | None = None


# ---------- /v1/audio/speech ----------

SpeechFormat = Literal["mp3", "opus", "aac", "flac", "wav", "pcm"]


class OaiSpeechRequest(BaseModel):
    model: str = Field(default="tts-1", description="Provider 名；tts-1/tts-1-hd 映射到默认")
    # 不用 Pydantic min_length：Pydantic 422 不走自定义 error handler，
    # 校验在端点内手工做以保证 OpenAI error envelope 格式一致。
    input: str = Field(max_length=10000)
    voice: str = Field(default="alloy")
    response_format: SpeechFormat = "mp3"
    speed: float = Field(default=1.0, ge=0.25, le=4.0)


# ---------- Error envelope ----------

OaiErrorType = Literal[
    "invalid_request_error",
    "authentication_error",
    "permission_error",
    "not_found_error",
    "rate_limit_error",
    "api_error",
    "server_error",
]


class OaiErrorBody(BaseModel):
    message: str
    type: OaiErrorType
    code: str | None = None
    param: str | None = None


class OaiErrorEnvelope(BaseModel):
    error: OaiErrorBody
