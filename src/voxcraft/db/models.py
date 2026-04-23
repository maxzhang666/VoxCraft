"""SQLModel ORM 定义。字段与约束依 architecture/db-schema.md。"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Column, Index
from sqlalchemy.dialects.sqlite import JSON
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Provider(SQLModel, table=True):
    __tablename__ = "providers"

    id: int | None = Field(default=None, primary_key=True)
    kind: str = Field(index=True)
    name: str = Field(unique=True, index=True)
    class_name: str
    config: dict = Field(default_factory=dict, sa_column=Column(JSON))
    is_default: bool = Field(default=False)
    enabled: bool = Field(default=True)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    __table_args__ = (
        Index("ix_provider_kind_default", "kind", "is_default"),
    )


class LlmProvider(SQLModel, table=True):
    __tablename__ = "llm_providers"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    base_url: str  # OpenAI 兼容端点，如 https://api.openai.com/v1
    api_key: str  # 明文入库；自托管场景用户自行保护 data/voxcraft.sqlite
    model: str  # 默认使用的模型名，如 gpt-4o-mini / deepseek-chat / qwen-turbo
    is_default: bool = Field(default=False)
    enabled: bool = Field(default=True)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class Job(SQLModel, table=True):
    __tablename__ = "jobs"

    id: str = Field(primary_key=True)
    kind: str = Field(index=True)
    status: str = Field(index=True)
    provider_name: str | None = None
    request: dict = Field(default_factory=dict, sa_column=Column(JSON))
    result: dict | None = Field(default=None, sa_column=Column(JSON))
    source_path: str | None = None  # 用户上传的原始音频；成功/失败均保留，供重试
    output_path: str | None = None
    output_extras: dict | None = Field(default=None, sa_column=Column(JSON))
    error_code: str | None = None
    error_message: str | None = None
    progress: float = Field(default=0.0)
    queue_position: int | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    __table_args__ = (
        Index("ix_jobs_kind_status_created", "kind", "status", "created_at"),
    )


class VoiceRef(SQLModel, table=True):
    __tablename__ = "voice_refs"

    id: str = Field(primary_key=True)
    speaker_name: str | None = None
    reference_audio_path: str
    provider_name: str
    created_at: datetime = Field(default_factory=_utcnow)


class AppSetting(SQLModel, table=True):
    __tablename__ = "app_settings"

    key: str = Field(primary_key=True)
    value: dict = Field(default_factory=dict, sa_column=Column(JSON))
    updated_at: datetime = Field(default_factory=_utcnow)


class Model(SQLModel, table=True):
    """模型库（v0.1.2，ADR-010）。独立于 Provider 表。

    status 生命周期：
      pending → downloading → ready
                         ↘ failed
                         ↘ cancelled → cleanup_pending → cancelled_final
    """
    __tablename__ = "models"

    id: int | None = Field(default=None, primary_key=True)
    catalog_key: str = Field(index=True, unique=True)
    source: str                                   # hf / ms / url / manual
    repo_id: str                                  # 对 manual 可为空字符串
    kind: str = Field(index=True)                 # asr / tts / cloning / separator / unknown
    local_path: str | None = None
    status: str = Field(default="pending", index=True)
    progress: float = Field(default=0.0)
    size_bytes: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
