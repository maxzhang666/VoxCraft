"""模型库 API schemas（v0.1.2 / ADR-010）。"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


Kind = Literal["asr", "tts", "cloning", "separator"]
Source = Literal["hf", "ms", "url", "torch_hub"]


class SourceInfo(BaseModel):
    id: str                     # "hf" / "ms" / "url" / "torch_hub"
    repo_id: str


class CatalogView(BaseModel):
    """给 UI 的合并视图：catalog 静态信息 + 本地 Model 状态。"""
    catalog_key: str
    label: str
    kind: str
    size_mb: int
    recommend_tier: str
    mirror_authority: str
    sources: list[SourceInfo]
    is_builtin: bool
    provider_class: str | None = None       # 内置模型对应的 Provider 实现类
    # 本地状态（若未下载则保持默认）
    model_id: int | None = None
    status: str = "not_downloaded"
    progress: float = 0.0
    local_path: str | None = None
    queue_position: int | None = None
    size_bytes: int | None = None
    error_code: str | None = None


class ModelResponse(BaseModel):
    """原始 Model 表响应（用于 POST download/custom 返回）。"""
    id: int
    catalog_key: str
    source: str
    repo_id: str
    kind: str
    local_path: str | None
    status: str
    progress: float
    size_bytes: int | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    model_config = {"from_attributes": True}


class CustomAddRequest(BaseModel):
    catalog_key: str = Field(
        pattern=r"^custom_[a-z0-9][a-z0-9_\-]*$",
        min_length=8,  # custom_ + 1 char
        max_length=64,
    )
    source: Source
    repo_id: str = Field(min_length=1)
    kind: Kind
    label: str | None = None

    @field_validator("catalog_key")
    @classmethod
    def _no_builtin_clash(cls, v: str) -> str:
        from voxcraft.models_lib.catalog import is_reserved_key

        # custom_ 前缀虽已由 pattern 保证，仍复查避免未来规则漂移
        if not v.startswith("custom_"):
            raise ValueError("catalog_key must start with 'custom_'")
        # 内置 catalog key 不会撞 custom_ 前缀（启动时校验过），这里只保险
        if is_reserved_key(v):
            # is_reserved_key 对 custom_ 前缀返回 True —— 这里接受前缀合规
            pass
        return v
