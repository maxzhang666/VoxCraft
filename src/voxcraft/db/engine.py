"""SQLModel engine 单例。"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import create_engine

from voxcraft.config import get_settings


def _ensure_parent(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    settings = get_settings()
    _ensure_parent(settings.db)
    return create_engine(
        f"sqlite:///{settings.db}",
        connect_args={"check_same_thread": False},
    )
