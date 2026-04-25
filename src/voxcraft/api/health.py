"""/health + /models 运维端点。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from voxcraft.api.schemas.system import GpuInfo, HealthResponse, ModelsResponse
from voxcraft.db.engine import get_engine
from voxcraft.db.models import Provider
from voxcraft.runtime.gpu import device_name, is_cuda_available, vram_usage_mb


router = APIRouter(tags=["health"])


def get_session():
    with Session(get_engine()) as s:
        yield s


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    available = is_cuda_available()
    if available:
        used_mb, total_mb = vram_usage_mb()
        gpu = GpuInfo(
            available=True,
            used_mb=used_mb,
            total_mb=total_mb,
            name=device_name(),
        )
    else:
        gpu = GpuInfo()
    return HealthResponse(status="ok", db=True, gpu=gpu)


@router.get("/models", response_model=ModelsResponse)
def models(session: Session = Depends(get_session)) -> ModelsResponse:
    rows = session.exec(select(Provider).where(Provider.enabled == True)).all()  # noqa: E712
    out = ModelsResponse()
    for p in rows:
        bucket = getattr(out, p.kind, None)
        if isinstance(bucket, list):
            bucket.append(p.name)
    return out
