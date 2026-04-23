"""/admin/models-library 路由（v0.1.2 / ADR-010）。"""
from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from sqlmodel import Session, select

from voxcraft.api.schemas.model_library import (
    CatalogView,
    CustomAddRequest,
    ModelResponse,
    SourceInfo,
)
from voxcraft.config import get_settings
from voxcraft.db.engine import get_engine
from voxcraft.db.models import Model, Provider
from voxcraft.errors import (
    CatalogKeyConflictError,
    ModelInUseError,
    ValidationError,
    VoxCraftError,
)
from voxcraft.models_lib.catalog import CATALOG, CatalogEntry, get_by_key


router = APIRouter(prefix="/admin/models-library", tags=["admin"])


def get_session():
    with Session(get_engine()) as s:
        yield s


def _get_service(request: Request):
    svc = getattr(request.app.state, "model_download_service", None)
    if svc is None:
        raise VoxCraftError(
            "ModelDownloadService not initialized",
            code="CONFIG_ERROR",
            status_code=500,
        )
    return svc


def _pick_default_source(entry: CatalogEntry) -> str:
    preferred = get_settings().preferred_source
    if preferred in entry.sources:
        return preferred
    for fallback in ("hf", "ms", "url", "torch_hub"):
        if fallback in entry.sources:
            return fallback
    return next(iter(entry.sources))


def _entry_to_view(
    entry: CatalogEntry, model: Model | None, service
) -> CatalogView:
    sources = [SourceInfo(id=sid, repo_id=repo) for sid, repo in entry.sources.items()]
    base = dict(
        catalog_key=entry.key,
        label=entry.label,
        kind=entry.kind,
        size_mb=entry.size_mb,
        recommend_tier=entry.recommend_tier,
        mirror_authority=entry.mirror_authority,
        sources=sources,
        is_builtin=True,
        provider_class=entry.provider_class,
    )
    if model is None:
        return CatalogView(**base)
    return CatalogView(
        **base,
        model_id=model.id,
        status=model.status,
        progress=model.progress,
        local_path=model.local_path,
        queue_position=service.queue_position(model.id) if model.id else None,
        size_bytes=model.size_bytes,
        error_code=model.error_code,
    )


def _model_to_custom_view(model: Model, service) -> CatalogView:
    """非内置 Model（custom_/manual_ 前缀）转为视图。"""
    source_id = model.source if model.source in ("hf", "ms", "url", "torch_hub") else "url"
    return CatalogView(
        catalog_key=model.catalog_key,
        label=model.catalog_key,
        kind=model.kind,
        size_mb=(model.size_bytes or 0) // (1024 * 1024),
        recommend_tier="mid",
        mirror_authority="official",
        sources=[SourceInfo(id=source_id, repo_id=model.repo_id or "")],
        is_builtin=False,
        model_id=model.id,
        status=model.status,
        progress=model.progress,
        local_path=model.local_path,
        queue_position=service.queue_position(model.id) if model.id else None,
        size_bytes=model.size_bytes,
        error_code=model.error_code,
    )


def _extract_provider_model_paths(config: dict) -> list[str]:
    paths: list[str] = []
    for key in ("model_path", "model_dir", "model"):
        val = config.get(key) if isinstance(config, dict) else None
        if isinstance(val, str):
            paths.append(val)
    return paths


# --- 端点 ----------------------------------------------------------------

@router.get("", response_model=list[CatalogView])
def list_library(
    request: Request,
    session: Session = Depends(get_session),
):
    service = _get_service(request)
    rows = {m.catalog_key: m for m in session.exec(select(Model)).all()}
    views: list[CatalogView] = []
    for entry in CATALOG:
        views.append(_entry_to_view(entry, rows.get(entry.key), service))
    seen_keys = {e.key for e in CATALOG}
    for key, m in rows.items():
        if key in seen_keys:
            continue
        views.append(_model_to_custom_view(m, service))
    return views


@router.post("/{catalog_key}/download", response_model=ModelResponse, status_code=202)
async def download_catalog(
    catalog_key: str,
    request: Request,
    source: str | None = Query(None),
    session: Session = Depends(get_session),
):
    entry = get_by_key(catalog_key)
    if entry is None:
        raise VoxCraftError(
            f"Unknown catalog key: {catalog_key}",
            code="CATALOG_KEY_NOT_FOUND",
            status_code=404,
        )
    chosen = source or _pick_default_source(entry)
    if chosen not in entry.sources:
        raise ValidationError(
            f"Source '{chosen}' not available for {catalog_key}",
            details={"available": list(entry.sources)},
        )

    existing = session.exec(
        select(Model).where(Model.catalog_key == catalog_key)
    ).first()
    if existing and existing.status in ("pending", "downloading", "ready"):
        raise VoxCraftError(
            f"Model already in state '{existing.status}'",
            code="MODEL_ALREADY_EXISTS",
            status_code=409,
            details={"model_id": existing.id, "status": existing.status},
        )
    # failed/cancelled 的可以重下 —— 先删旧行
    if existing:
        session.delete(existing)
        session.commit()

    service = _get_service(request)
    model_id = await service.enqueue(
        catalog_key=catalog_key,
        source=chosen,
        repo_id=entry.sources[chosen],
        kind=entry.kind,
    )
    with Session(get_engine()) as s:
        return s.get(Model, model_id)


@router.post("/custom", response_model=ModelResponse, status_code=202)
async def add_custom(
    data: CustomAddRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    existing = session.exec(
        select(Model).where(Model.catalog_key == data.catalog_key)
    ).first()
    if existing:
        raise CatalogKeyConflictError(
            f"Model with catalog_key '{data.catalog_key}' already exists",
            details={"model_id": existing.id},
        )
    service = _get_service(request)
    model_id = await service.enqueue(
        catalog_key=data.catalog_key,
        source=data.source,
        repo_id=data.repo_id,
        kind=data.kind,
    )
    with Session(get_engine()) as s:
        return s.get(Model, model_id)


@router.delete("/{model_id}", status_code=204)
def delete_model(
    model_id: int,
    session: Session = Depends(get_session),
):
    m = session.get(Model, model_id)
    if m is None:
        raise VoxCraftError(
            f"Model {model_id} not found",
            code="MODEL_NOT_FOUND",
            status_code=404,
        )

    # 级联检查：Provider 引用
    refs: list[str] = []
    if m.local_path:
        for p in session.exec(select(Provider)).all():
            for path in _extract_provider_model_paths(p.config):
                if path == m.local_path or path.startswith(str(m.local_path) + "/"):
                    refs.append(p.name)
                    break
    if refs:
        raise ModelInUseError(
            f"Model {m.catalog_key} in use by {len(refs)} Provider(s)",
            details={"providers": refs},
        )

    # 删磁盘 + DB
    if m.local_path:
        p = Path(m.local_path)
        if p.exists():
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
    session.delete(m)
    session.commit()


@router.post("/{model_id}/cancel", status_code=202)
async def cancel_download(
    model_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    m = session.get(Model, model_id)
    if m is None:
        raise VoxCraftError(
            f"Model {model_id} not found",
            code="MODEL_NOT_FOUND",
            status_code=404,
        )
    service = _get_service(request)
    await service.cancel(model_id)
    return {"ok": True}
