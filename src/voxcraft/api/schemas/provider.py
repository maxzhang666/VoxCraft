"""Provider 管理 schemas。"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ProviderKind = Literal["asr", "tts", "cloning", "separator"]


class ProviderCreate(BaseModel):
    kind: ProviderKind
    name: str = Field(pattern=r"^[a-z0-9_\-]+$", min_length=1, max_length=64)
    class_name: str
    config: dict = Field(default_factory=dict)
    is_default: bool = False
    enabled: bool = True


class ProviderUpdate(BaseModel):
    config: dict | None = None
    is_default: bool | None = None
    enabled: bool | None = None


class ProviderResponse(BaseModel):
    id: int
    kind: str
    name: str
    class_name: str
    config: dict
    is_default: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProviderTestResult(BaseModel):
    ok: bool
    provider: str
    detail: str | None = None


class ConfigFieldSchema(BaseModel):
    key: str
    label: str
    type: Literal["path", "enum", "str", "int", "bool"]
    required: bool = False
    default: object | None = None
    options: list[str] | None = None
    help: str | None = None


class ProviderClassSchema(BaseModel):
    class_name: str
    label: str
    kind: ProviderKind
    fields: list[ConfigFieldSchema]
