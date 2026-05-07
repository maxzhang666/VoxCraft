"""TTS 请求/响应 schemas。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TtsGenerationParams(BaseModel):
    """生成时可调的采样/切分参数。每次合成请求独立指定，不进 Provider 全局 config。

    所有字段可选——不传走 Provider 默认值。Provider 实现忽略不认识的字段。
    当前 cloning 路径已下线，主要保留以便未来 TTS Provider 扩展沿用。
    """
    top_k: int | None = Field(None, ge=1, le=100)
    top_p: float | None = Field(None, gt=0, le=1.0)
    temperature: float | None = Field(None, gt=0, le=2.0)
    text_lang: str | None = None  # 目标输出语言；不传默认 "zh"


class TtsRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    voice_id: str
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    format: Literal["wav", "mp3", "ogg"] = "wav"
    provider: str | None = None
    # 生成时调采样：不传走 Provider 默认；传则覆盖
    generation: TtsGenerationParams | None = None


class VoiceSchema(BaseModel):
    id: str
    language: str
    gender: str | None = None
    provider_name: str                    # 归属 Provider；前端按此过滤
    # 仅保留 preset——cloned 路径已下线
    source: Literal["preset"] = "preset"


class VoicesResponse(BaseModel):
    voices: list[VoiceSchema]
