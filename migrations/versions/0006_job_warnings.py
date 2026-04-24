"""job_warnings: jobs.warnings JSON 字段（v0.4.0 / ADR-014 软降级记录）。

幂等：若列已存在则跳过。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def _has_column(bind, table: str, column: str) -> bool:
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind, "jobs", "warnings"):
        return
    op.add_column("jobs", sa.Column("warnings", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind, "jobs", "warnings"):
        op.drop_column("jobs", "warnings")
