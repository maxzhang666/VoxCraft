"""LLM Provider 管理 schemas（v0.3.0 / plans/voxcraft-llm-integration）。

关键约束：
- `api_key` 在 `Create` 必填；`Update` 可选
- **Response 绝不回显 `api_key`**（Pydantic model 直接不声明此字段）
- 自托管场景：DB 明文存储，用户自行保护 data/voxcraft.sqlite
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class LlmProviderCreate(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9_\-]+$", min_length=1, max_length=64)
    base_url: str = Field(min_length=1)
    api_key: str = Field(min_length=1)
    model: str = Field(min_length=1)
    is_default: bool = False
    enabled: bool = True


class LlmProviderUpdate(BaseModel):
    """所有字段 optional；`api_key` 省略或空字符串 = 保持原值。"""

    base_url: str | None = None
    api_key: str | None = None  # 空字符串/None 均不更新
    model: str | None = None
    is_default: bool | None = None
    enabled: bool | None = None


class ProbeModelsRequest(BaseModel):
    """拉取 OpenAI 兼容端点的可用模型列表。

    鉴权来源二选一（至少一个）：
    - 直接传 `api_key`（新建场景：用户已填 API Key 但未保存）
    - 传 `use_id`：用该 Provider 在 DB 的 api_key（编辑场景：不暴露已存 key）
    """

    base_url: str = Field(min_length=1)
    api_key: str | None = None
    use_id: int | None = None


class ProbeModelsResponse(BaseModel):
    models: list[str]


class LlmProviderResponse(BaseModel):
    """Response 刻意不声明 `api_key` 字段——即使 DB 行有，序列化时自动省略。"""

    id: int
    name: str
    base_url: str
    model: str
    is_default: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
