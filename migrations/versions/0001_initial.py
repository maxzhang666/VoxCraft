"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-19
"""
from __future__ import annotations

from alembic import op
from sqlmodel import SQLModel

import voxcraft.db.models  # noqa: F401  注册所有表到 metadata

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    SQLModel.metadata.create_all(op.get_bind())


def downgrade() -> None:
    SQLModel.metadata.drop_all(op.get_bind())
