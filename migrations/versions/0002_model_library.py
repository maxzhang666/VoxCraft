"""model_library: 新增 models 表（v0.1.2 / ADR-010）

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-21

注意：0001 使用 SQLModel.metadata.create_all() 懒人模式，会把当前 metadata 里
所有表建出（含本文件新增的 Model）。故本 0002 需幂等——检测表存在则跳过。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


_INDEXES = [
    ("ix_models_catalog_key", ["catalog_key"], True),
    ("ix_models_kind", ["kind"], False),
    ("ix_models_status", ["status"], False),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "models" not in inspector.get_table_names():
        op.create_table(
            "models",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("catalog_key", sa.String, nullable=False),
            sa.Column("source", sa.String, nullable=False),
            sa.Column("repo_id", sa.String, nullable=False),
            sa.Column("kind", sa.String, nullable=False),
            sa.Column("local_path", sa.String, nullable=True),
            sa.Column("status", sa.String, nullable=False, server_default="pending"),
            sa.Column("progress", sa.Float, nullable=False, server_default="0"),
            sa.Column("size_bytes", sa.Integer, nullable=True),
            sa.Column("error_code", sa.String, nullable=True),
            sa.Column("error_message", sa.String, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False),
        )

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("models")}
    for name, cols, uniq in _INDEXES:
        if name not in existing_indexes:
            op.create_index(name, "models", cols, unique=uniq)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("models")}
    for name, _, _ in _INDEXES:
        if name in existing_indexes:
            op.drop_index(name, table_name="models")
    if "models" in inspector.get_table_names():
        op.drop_table("models")
