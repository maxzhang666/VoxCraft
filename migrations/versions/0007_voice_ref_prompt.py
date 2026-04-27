"""voice_refs.prompt_text + prompt_lang：把克隆 Provider 的 prompt 转写文字
+ 语言提到 voice 粒度（之前误放在 Provider 全局 config，导致用户每换一个
不同语种音色都要改 Provider 设置）。

幂等：列已存在则跳过。两列均 nullable，向后兼容已有 voice_refs 行。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def _has_column(bind, table: str, column: str) -> bool:
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_column(bind, "voice_refs", "prompt_text"):
        op.add_column("voice_refs", sa.Column("prompt_text", sa.Text(), nullable=True))
    if not _has_column(bind, "voice_refs", "prompt_lang"):
        op.add_column("voice_refs", sa.Column("prompt_lang", sa.String(16), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind, "voice_refs", "prompt_lang"):
        op.drop_column("voice_refs", "prompt_lang")
    if _has_column(bind, "voice_refs", "prompt_text"):
        op.drop_column("voice_refs", "prompt_text")
