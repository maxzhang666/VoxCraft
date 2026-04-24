"""/admin/providers 与 /admin/llm CRUD。LLM 管理延到 v0.5+ 占位。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session, select

from voxcraft.api.schemas.provider import (
    ConfigFieldSchema,
    ProviderClassSchema,
    ProviderCreate,
    ProviderResponse,
    ProviderTestResult,
    ProviderUpdate,
)
from voxcraft.db.engine import get_engine
from voxcraft.db.models import Provider
from voxcraft.errors import ValidationError, VoxCraftError
from voxcraft.providers.registry import PROVIDER_REGISTRY, instantiate, resolve


router = APIRouter(prefix="/admin/providers", tags=["admin"])


def get_session():
    with Session(get_engine()) as s:
        yield s


def _not_found(id: int) -> VoxCraftError:
    return VoxCraftError(
        f"Provider not found: {id}",
        code="PROVIDER_NOT_FOUND",
        status_code=404,
    )


@router.get("", response_model=list[ProviderResponse])
def list_providers(
    kind: str | None = None, session: Session = Depends(get_session)
):
    q = select(Provider)
    if kind:
        q = q.where(Provider.kind == kind)
    return session.exec(q).all()


@router.get("/classes", response_model=list[ProviderClassSchema])
def list_provider_classes(kind: str | None = None) -> list[ProviderClassSchema]:
    """返回 registry 中所有可用 Provider 类及其 config schema，驱动前端动态表单。"""
    out: list[ProviderClassSchema] = []
    for class_name, cls in PROVIDER_REGISTRY.items():
        if kind and cls.kind != kind:
            continue
        out.append(
            ProviderClassSchema(
                class_name=class_name,
                label=cls.LABEL or class_name,
                kind=cls.kind,  # type: ignore[arg-type]
                fields=[
                    ConfigFieldSchema(
                        key=f.key,
                        label=f.label,
                        type=f.type,
                        required=f.required,
                        default=f.default,
                        options=list(f.options) if f.options else None,
                        help=f.help,
                    )
                    for f in cls.CONFIG_SCHEMA
                ],
                capabilities=sorted(cls.CAPABILITIES),
            )
        )
    return out


@router.post("", response_model=ProviderResponse, status_code=201)
def create_provider(
    data: ProviderCreate, session: Session = Depends(get_session)
):
    if data.class_name not in PROVIDER_REGISTRY:
        raise VoxCraftError(
            f"Unknown provider class: {data.class_name}",
            code="PROVIDER_UNKNOWN",
            status_code=400,
        )
    p = Provider(**data.model_dump())
    session.add(p)
    try:
        session.commit()
    except Exception as e:
        session.rollback()
        raise ValidationError(
            f"Failed to create provider: {e}",
            details={"name": data.name},
        ) from e
    session.refresh(p)
    return p


@router.patch("/{id}", response_model=ProviderResponse)
def update_provider(
    id: int,
    data: ProviderUpdate,
    session: Session = Depends(get_session),
):
    p = session.get(Provider, id)
    if p is None:
        raise _not_found(id)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    session.commit()
    session.refresh(p)
    return p


@router.delete("/{id}", status_code=204)
def delete_provider(
    id: int, session: Session = Depends(get_session)
) -> None:
    p = session.get(Provider, id)
    if p is None:
        raise _not_found(id)
    session.delete(p)
    session.commit()


@router.post("/{id}/set-default", response_model=ProviderResponse)
def set_default(
    id: int, session: Session = Depends(get_session)
):
    p = session.get(Provider, id)
    if p is None:
        raise _not_found(id)
    others = session.exec(
        select(Provider).where(Provider.kind == p.kind, Provider.id != id)
    ).all()
    for o in others:
        o.is_default = False
    p.is_default = True
    session.commit()
    session.refresh(p)
    return p


@router.post("/{id}/test", response_model=ProviderTestResult)
async def test_provider(
    id: int, request: Request, session: Session = Depends(get_session)
):
    """真实探活：构造 Provider 实例并通过 LRU 触发 load()，验证模型可装入显存。

    走 `scheduler.run` 以避免与业务推理并发。失败时返回 ok=False + 错误详情，
    前端据此显示 Toast.error。
    """
    p = session.get(Provider, id)
    if p is None:
        raise _not_found(id)

    try:
        resolve(p.class_name)  # 先快速校验 class 存在，报错更精准
        inst = instantiate(p.class_name, name=p.name, config=p.config)
    except VoxCraftError as e:
        return ProviderTestResult(ok=False, provider=p.name, detail=f"[{e.code}] {e.message}")

    scheduler = request.app.state.scheduler
    lru = request.app.state.lru

    try:
        async def probe():
            await lru.ensure_loaded(inst)

        await scheduler.run(probe)
    except VoxCraftError as e:
        return ProviderTestResult(ok=False, provider=p.name, detail=f"[{e.code}] {e.message}")
    except BaseException as e:
        return ProviderTestResult(ok=False, provider=p.name, detail=f"[PROBE_FAILED] {e}")

    return ProviderTestResult(ok=True, provider=p.name, detail="model loaded")
