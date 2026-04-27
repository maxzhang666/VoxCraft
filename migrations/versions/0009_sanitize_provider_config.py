"""把每行 providers.config 缩减到对应 Provider 类的 CONFIG_SCHEMA 白名单——
清掉之前在 voice/generation 重构后残留的 stale key（如 GPT-SoVITS 上还挂着
prompt_text="克隆" / top_p="1.0" 这种旧字段污染）。

无法 import Provider 类 → 跳过该行（容错；class_name 漂移时不阻塞迁移）。
"""
from __future__ import annotations

import json

from alembic import op
from sqlalchemy import text


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def _allowed_keys_for(class_name: str) -> set[str] | None:
    """返回 Provider 类 CONFIG_SCHEMA 里声明的 key 集合；类不存在返回 None（跳过）。"""
    try:
        # 延迟 import：迁移时 voxcraft 包通常已 importable，但兜底防 alembic 独立运行场景
        from voxcraft.providers.registry import PROVIDER_REGISTRY  # noqa: PLC0415
    except ImportError:
        return None
    cls = PROVIDER_REGISTRY.get(class_name)
    if cls is None:
        return None
    return {f.key for f in getattr(cls, "CONFIG_SCHEMA", [])}


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        text("SELECT id, class_name, config FROM providers")
    ).fetchall()
    for row in rows:
        pid, class_name, raw = row
        # SQLite/JSON column 在 alembic 原生 SQL 下既可能是 dict（PG）也可能是 str（SQLite）
        if isinstance(raw, str):
            try:
                cfg = json.loads(raw)
            except (TypeError, ValueError):
                continue
        elif isinstance(raw, dict):
            cfg = raw
        else:
            continue

        allowed = _allowed_keys_for(class_name)
        if allowed is None:
            continue
        cleaned = {k: v for k, v in cfg.items() if k in allowed}
        if cleaned == cfg:
            continue
        # 落回 JSON 字符串；server-side updated_at 触发器（如有）会自动更新
        bind.execute(
            text("UPDATE providers SET config = :cfg WHERE id = :id"),
            {"cfg": json.dumps(cleaned, ensure_ascii=False), "id": pid},
        )


def downgrade() -> None:
    # 不可逆：丢弃的 stale key 没保留备份。本质是数据清理而非 schema 变更。
    pass
