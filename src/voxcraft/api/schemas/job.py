"""Job schemas。"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class JobStatus(str, Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class JobResponse(BaseModel):
    id: str
    kind: str
    status: str
    provider_name: str | None = None
    request: dict
    result: dict | None = None
    output_path: str | None = None
    output_extras: dict | None = None
    error_code: str | None = None
    error_message: str | None = None
    progress: float
    queue_position: int | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    model_config = {"from_attributes": True}


class JobSubmitResponse(BaseModel):
    """异步提交端点的响应（/asr /tts /tts/clone /separate /jobs/{id}/retry）。"""

    job_id: str
    status: str
