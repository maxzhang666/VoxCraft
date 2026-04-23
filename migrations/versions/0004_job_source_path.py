"""job_source_path: jobs 表加 source_path（全异步化 + 失败重试）

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-22

幂等：若列已存在则跳过。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _existing_columns(bind) -> set[str]:
    inspector = sa.inspect(bind)
    if "jobs" not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns("jobs")}


def upgrade() -> None:
    bind = op.get_bind()
    if "source_path" not in _existing_columns(bind):
        op.add_column("jobs", sa.Column("source_path", sa.String(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if "source_path" in _existing_columns(bind):
        op.drop_column("jobs", "source_path")
