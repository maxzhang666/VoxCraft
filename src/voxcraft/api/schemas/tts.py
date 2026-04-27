"""TTS 请求/响应 schemas。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TtsGenerationParams(BaseModel):
    """生成时可调的采样/切分参数。每次合成请求独立指定，不进 Provider 全局 config。

    所有字段可选——不传走 Provider 默认值。Provider 会按各自模型的范围消化：
    - VoxCPM 用 cfg_value / inference_timesteps
    - GPT-SoVITS 用 top_k / top_p / temperature / text_split_method / text_lang
    其他 Provider 忽略不认识的字段。
    """
    top_k: int | None = Field(None, ge=1, le=100)
    top_p: float | None = Field(None, gt=0, le=1.0)
    temperature: float | None = Field(None, gt=0, le=2.0)
    text_split_method: str | None = None  # GPT-SoVITS: cut0..cut5
    # text_lang / prompt_lang：生成时可调的语言代码。
    # - text_lang：目标输出语言；不传默认 "zh"
    # - prompt_lang：参考音频语言。voice_refs 里有默认值（抽取时填的），
    #   生成时传则覆盖默认——用户可以在调试时换 auto/zh/en 看哪个准
    text_lang: str | None = None
    prompt_lang: str | None = None
    cfg_value: float | None = Field(None, gt=0)             # VoxCPM
    inference_timesteps: int | None = Field(None, ge=1, le=100)  # VoxCPM


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
    sample_url: str | None = None
    provider_name: str                    # 归属 Provider；前端按此过滤
    source: Literal["preset", "cloned"]   # preset=Provider 内置单音色；cloned=VoiceRef
    # cloned voice 才有：参考音频转写 + 语言
    prompt_text: str | None = None
    prompt_lang: str | None = None


class VoicesResponse(BaseModel):
    voices: list[VoiceSchema]


class VoiceExtractResponse(BaseModel):
    """POST /api/tts/voices/extract 返回：抽取声纹后的 voice 信息。"""

    voice_id: str
    speaker_name: str | None = None
    provider_name: str
    reference_audio_path: str
    duration_seconds: float | None = None
    prompt_text: str | None = None
    prompt_lang: str | None = None
