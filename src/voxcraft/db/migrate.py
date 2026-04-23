"""Alembic 程序化调用封装，用于应用启动时自动升级。"""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def run_upgrade_head() -> None:
    cfg = Config(str(_PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_PROJECT_ROOT / "migrations"))
    command.upgrade(cfg, "head")
