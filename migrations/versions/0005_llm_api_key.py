"""llm_api_key: llm_providers.api_key_env → api_key（v0.3.0 / plans/voxcraft-llm-integration）

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-23

当前无任何 LLM 配置记录（功能未启用），直接 drop 旧列 + add 新列，零数据风险。
幂等：若已为新 schema 则跳过。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _existing_columns(bind) -> set[str]:
    inspector = sa.inspect(bind)
    if "llm_providers" not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns("llm_providers")}


def upgrade() -> None:
    bind = op.get_bind()
    cols = _existing_columns(bind)
    if not cols:
        return  # 表不存在（首次上线），0001 建表已是新 schema
    if "api_key" not in cols:
        op.add_column("llm_providers", sa.Column("api_key", sa.String(), nullable=False, server_default=""))
    if "api_key_env" in cols:
        op.drop_column("llm_providers", "api_key_env")


def downgrade() -> None:
    bind = op.get_bind()
    cols = _existing_columns(bind)
    if not cols:
        return
    if "api_key_env" not in cols:
        op.add_column("llm_providers", sa.Column("api_key_env", sa.String(), nullable=False, server_default=""))
    if "api_key" in cols:
        op.drop_column("llm_providers", "api_key")
