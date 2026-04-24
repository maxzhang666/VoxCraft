"""/admin/llm CRUD（v0.3.0 / plans/voxcraft-llm-integration）。

LLM Provider 管理端点。独立模块——与 /admin/providers（音频 Provider 管理）解耦。

- POST /admin/llm                          新增
- GET  /admin/llm                          列表
- PATCH /admin/llm/{id}                    更新（api_key 空值 = 保持不变）
- DELETE /admin/llm/{id}
- POST /admin/llm/{id}/set-default         设默认（同表互斥）

**响应不含 api_key**——由 `LlmProviderResponse` schema 保证。

ADR-011 业务异步化不适用于 /admin/*；本模块端点同步即可。
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from voxcraft.api.schemas.llm import (
    LlmProviderCreate,
    LlmProviderResponse,
    LlmProviderUpdate,
    ProbeModelsRequest,
    ProbeModelsResponse,
)
from voxcraft.db.engine import get_engine
from voxcraft.db.models import LlmProvider
from voxcraft.errors import ValidationError, VoxCraftError
from voxcraft.llm.client import LlmClient


router = APIRouter(prefix="/admin/llm", tags=["admin-llm"])


def get_session():
    with Session(get_engine()) as s:
        yield s


def _not_found(id: int) -> VoxCraftError:
    return VoxCraftError(
        f"LLM provider not found: {id}",
        code="LLM_PROVIDER_NOT_FOUND",
        status_code=404,
    )


@router.get("", response_model=list[LlmProviderResponse])
def list_llm(session: Session = Depends(get_session)):
    return session.exec(select(LlmProvider)).all()


@router.post("", response_model=LlmProviderResponse, status_code=201)
def create_llm(data: LlmProviderCreate, session: Session = Depends(get_session)):
    row = LlmProvider(**data.model_dump())
    session.add(row)
    try:
        session.commit()
    except Exception as e:
        session.rollback()
        raise ValidationError(
            f"Failed to create LLM provider: {e}",
            details={"name": data.name},
        ) from e
    session.refresh(row)
    return row


@router.patch("/{id}", response_model=LlmProviderResponse)
def update_llm(
    id: int, data: LlmProviderUpdate, session: Session = Depends(get_session),
):
    row = session.get(LlmProvider, id)
    if row is None:
        raise _not_found(id)
    patch = data.model_dump(exclude_unset=True)
    # api_key 空字符串 = 保持原值（编辑场景留空即可）
    if "api_key" in patch and (patch["api_key"] is None or patch["api_key"] == ""):
        patch.pop("api_key")
    for k, v in patch.items():
        setattr(row, k, v)
    row.updated_at = datetime.now(UTC)
    session.commit()
    session.refresh(row)
    return row


@router.delete("/{id}", status_code=204)
def delete_llm(id: int, session: Session = Depends(get_session)) -> None:
    row = session.get(LlmProvider, id)
    if row is None:
        raise _not_found(id)
    session.delete(row)
    session.commit()


@router.post("/probe-models", response_model=ProbeModelsResponse)
def probe_models(
    body: ProbeModelsRequest, session: Session = Depends(get_session),
) -> ProbeModelsResponse:
    """拉取 OpenAI 兼容端点的可用模型列表，驱动前端 Model 下拉。

    鉴权：`api_key` 优先；否则用 `use_id` 指向 Provider 的已存 api_key。
    """
    api_key = (body.api_key or "").strip()
    if not api_key:
        if body.use_id is None:
            raise ValidationError(
                "api_key or use_id required",
                details={"field": "api_key"},
            )
        row = session.get(LlmProvider, body.use_id)
        if row is None:
            raise _not_found(body.use_id)
        api_key = row.api_key
    # 10s 超时足够大多数 /v1/models 调用；不可配置以保持端点简洁
    client = LlmClient(
        base_url=body.base_url, api_key=api_key, model="", timeout=10.0,
    )
    models = client.list_models()
    return ProbeModelsResponse(models=models)


@router.post("/{id}/set-default", response_model=LlmProviderResponse)
def set_default_llm(id: int, session: Session = Depends(get_session)):
    row = session.get(LlmProvider, id)
    if row is None:
        raise _not_found(id)
    # 同表互斥：其他全设为 False
    others = session.exec(select(LlmProvider).where(LlmProvider.id != id)).all()
    for o in others:
        o.is_default = False
    row.is_default = True
    row.updated_at = datetime.now(UTC)
    session.commit()
    session.refresh(row)
    return row
