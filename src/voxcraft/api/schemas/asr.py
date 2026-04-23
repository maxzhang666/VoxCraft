"""ASR schemas。"""
from __future__ import annotations

from pydantic import BaseModel


class AsrSegmentSchema(BaseModel):
    start: float
    end: float
    text: str


class AsrResponse(BaseModel):
    segments: list[AsrSegmentSchema]
    language: str
    duration: float
    provider: str
