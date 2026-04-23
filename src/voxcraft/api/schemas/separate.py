"""Separator 响应 schema。"""
from __future__ import annotations

from pydantic import BaseModel


class SeparateResponse(BaseModel):
    job_id: str
    vocals_url: str
    instrumental_url: str
    provider: str
