"""model_timestamps: models 表加 started_at / finished_at（v0.1.2）

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-21

幂等：若列已存在（例如 0001 懒人模式 metadata.create_all 已建），则跳过。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _existing_columns(bind) -> set[str]:
    inspector = sa.inspect(bind)
    if "models" not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns("models")}


def upgrade() -> None:
    bind = op.get_bind()
    existing = _existing_columns(bind)
    if "started_at" not in existing:
        op.add_column("models", sa.Column("started_at", sa.DateTime, nullable=True))
    if "finished_at" not in existing:
        op.add_column("models", sa.Column("finished_at", sa.DateTime, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    existing = _existing_columns(bind)
    if "finished_at" in existing:
        op.drop_column("models", "finished_at")
    if "started_at" in existing:
        op.drop_column("models", "started_at")
