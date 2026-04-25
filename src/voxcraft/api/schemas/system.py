"""系统 / 运维 schemas。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class GpuInfo(BaseModel):
    available: bool = False
    used_mb: int = 0
    total_mb: int = 0
    name: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "down"] = "ok"
    db: bool = True
    gpu: GpuInfo = GpuInfo()


class ModelsResponse(BaseModel):
    asr: list[str] = []
    tts: list[str] = []
    cloning: list[str] = []
    separator: list[str] = []
    translation: list[str] = []
