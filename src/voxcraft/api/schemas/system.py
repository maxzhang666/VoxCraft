"""系统 / 运维 schemas。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "down"] = "ok"
    db: bool = True
    gpu: bool = False


class ModelsResponse(BaseModel):
    asr: list[str] = []
    tts: list[str] = []
    cloning: list[str] = []
    separator: list[str] = []
    translation: list[str] = []
