"""/health + /models 运维端点。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from voxcraft.api.schemas.system import HealthResponse, ModelsResponse
from voxcraft.db.engine import get_engine
from voxcraft.db.models import Provider
from voxcraft.runtime.gpu import is_cuda_available


router = APIRouter(tags=["health"])


def get_session():
    with Session(get_engine()) as s:
        yield s


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", db=True, gpu=is_cuda_available())


@router.get("/models", response_model=ModelsResponse)
def models(session: Session = Depends(get_session)) -> ModelsResponse:
    rows = session.exec(select(Provider).where(Provider.enabled == True)).all()  # noqa: E712
    out = ModelsResponse()
    for p in rows:
        bucket = getattr(out, p.kind, None)
        if isinstance(bucket, list):
            bucket.append(p.name)
    return out
