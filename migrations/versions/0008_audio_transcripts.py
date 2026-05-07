"""voice = 纯音色（reference clip + speaker），prompt_text/prompt_lang 不再属于
voice 元数据本身——它们只是"参考音频里说了什么"这个事实的派生属性。

新 audio_transcripts 表（key=audio_path）作为转写缓存：抽取声纹时由 ASR 自动
填，零手填；GPT-SoVITS / VoxCPM 1.x 等需要参考转写的 Provider 在合成时由
worker 反查注入 voice_metadata。voice_refs 上的两列删掉——既然 audio_path
是 1:1 与 voice 对应，转写跟着 audio_path 走，避免"voice 抽象里塞模型实现细节"。

幂等：列存在才删；表存在才跳建。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def _has_column(bind, table: str, column: str) -> bool:
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def _has_table(bind, table: str) -> bool:
    return table in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    bind = op.get_bind()

    # 1) 新建 audio_transcripts 缓存表（即便 cloning 后续整体下线，本表已迁移过的库
    #    会保留为 orphan；不再删除以保持迁移链单调）
    if not _has_table(bind, "audio_transcripts"):
        op.create_table(
            "audio_transcripts",
            sa.Column("audio_path", sa.String(length=512), primary_key=True),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("language", sa.String(length=16), nullable=True),
            sa.Column("asr_provider", sa.String(length=128), nullable=True),
            sa.Column(
                "computed_at", sa.DateTime(),
                server_default=sa.func.current_timestamp(), nullable=False,
            ),
        )

    # 2) voice_refs 去掉 prompt_text / prompt_lang——表自身可能不存在（fresh DB
    #    不再有此 ORM 模型），整段直接 no-op
    if not _has_table(bind, "voice_refs"):
        return
    if _has_column(bind, "voice_refs", "prompt_lang"):
        op.drop_column("voice_refs", "prompt_lang")
    if _has_column(bind, "voice_refs", "prompt_text"):
        op.drop_column("voice_refs", "prompt_text")


def downgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "voice_refs"):
        if not _has_column(bind, "voice_refs", "prompt_text"):
            op.add_column("voice_refs", sa.Column("prompt_text", sa.Text(), nullable=True))
        if not _has_column(bind, "voice_refs", "prompt_lang"):
            op.add_column("voice_refs", sa.Column("prompt_lang", sa.String(16), nullable=True))
    if _has_table(bind, "audio_transcripts"):
        op.drop_table("audio_transcripts")
