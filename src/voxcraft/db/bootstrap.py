"""启动时模型目录扫描。幂等。

历史上曾在此 seed 4 个默认 Provider，但 model_path 全是占位字符串（指向未下载的目录），
首次启动后「模型管理」就出现一堆探活必败的幻觉行。改为完全空白启动：
用户走「模型库下载 → 模型管理选已下载模型自动建 Provider」的闭环。
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, select

from voxcraft.config import get_settings
from voxcraft.db.models import Model


def _dir_size_bytes(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _purge_duplicate_manual_rows(session: Session) -> int:
    """一次性清理旧 scan bug 产生的 manual_* 孤儿。

    规则：若某条 `manual_*` Model 的 local_path 与一条**非 manual_** Model 的
    local_path 解析后指向同一目录，则前者是重复记录，删除。

    表未建时（首次启动、测试环境等）静默跳过。
    """
    from sqlalchemy.exc import OperationalError

    try:
        rows = session.exec(select(Model)).all()
    except OperationalError:
        return 0

    def _resolve(p: str | None) -> Path | None:
        if not p:
            return None
        try:
            return Path(p).resolve()
        except OSError:
            return None

    canonical_paths: set[Path] = set()
    for m in rows:
        if m.catalog_key.startswith("manual_"):
            continue
        rp = _resolve(m.local_path)
        if rp is not None:
            canonical_paths.add(rp)

    purged = 0
    for m in rows:
        if not m.catalog_key.startswith("manual_"):
            continue
        rp = _resolve(m.local_path)
        if rp is None:
            continue
        if rp in canonical_paths:
            session.delete(m)
            purged += 1
    if purged:
        session.commit()
    return purged


def scan_existing_models(engine: Engine) -> int:
    """扫描 MODELS_DIR，把 **未被任何 Model 记录认领** 的子目录补成 `manual_*` 行。

    去重策略（修复 v0.4.0 前的 bug）：按 `Model.local_path` 占用关系判定，
    而非单纯比较 `catalog_key` 字符串。原实现只比 `manual_<name>` vs 已存 key，
    导致每个下载好的 catalog 模型（如 `whisper-tiny` → `models/whisper-tiny/`）
    都会被再次补成 `manual_whisper-tiny` 孤儿条目。

    - 仅扫描一级子目录；文件忽略
    - catalog_key 使用 `manual_{subdir.name}`，`manual_` 前缀与内置 key 隔离
    - kind 默认 `unknown`，UI 可后续让用户分类
    - 幂等：目录已被现有 Model 记录的 local_path 占用 → 跳过；catalog_key 已存在 → 跳过

    返回新增行数。
    """
    models_dir = get_settings().models_dir

    with Session(engine) as session:
        # 先清一次历史孤儿：manual_* 记录的 local_path 与某条非 manual_ 记录相同
        # → 删 manual_ 那条（之前 scan bug 产生的重复）
        _purge_duplicate_manual_rows(session)

        if not models_dir.exists():
            return 0

        all_models = session.exec(select(Model)).all()
        existing_keys = {m.catalog_key for m in all_models}
        # 已被 Model 记录占用的目录（绝对路径集合）——核心去重依据
        claimed_dirs: set[Path] = set()
        for m in all_models:
            if not m.local_path:
                continue
            try:
                claimed_dirs.add(Path(m.local_path).resolve())
            except OSError:
                # 不存在或无法解析的路径忽略
                pass

        inserted = 0
        for subdir in sorted(models_dir.iterdir()):
            if not subdir.is_dir():
                continue
            try:
                sub_resolved = subdir.resolve()
            except OSError:
                continue
            if sub_resolved in claimed_dirs:
                # 已由某 Model 记录认领（通常是 catalog 下载成果），跳过
                continue
            key = f"manual_{subdir.name}"
            if key in existing_keys:
                continue
            session.add(
                Model(
                    catalog_key=key,
                    source="manual",
                    repo_id="",
                    kind="unknown",
                    local_path=str(subdir),
                    status="ready",
                    progress=1.0,
                    size_bytes=_dir_size_bytes(subdir),
                )
            )
            inserted += 1
        session.commit()
    return inserted
