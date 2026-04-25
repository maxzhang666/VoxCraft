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
from voxcraft.db.models import Job, Model


def mark_stale_jobs_interrupted(engine: Engine) -> int:
    """把上次进程残留的 running / pending Job 标记为 interrupted。

    重启后 scheduler 实例是新的，老 Job 不会被自动捡起；DB 里的状态却还停留在
    running，UI 表现为"队列卡住"。本函数在 lifespan 早期把它们标为 interrupted，
    用户可在 UI 手动点"继续"走 retry 路径——**不自动重跑**，因为该任务可能正是
    把上一次进程拖崩的元凶，自动重试会反复触发。

    返回受影响行数。
    """
    with Session(engine) as session:
        rows = session.exec(
            select(Job).where(Job.status.in_(["running", "pending"]))  # type: ignore[attr-defined]
        ).all()
        for j in rows:
            j.status = "interrupted"
            j.error_code = "INTERRUPTED"
            j.error_message = (
                "进程在该任务运行期间退出（exit/SIGKILL/重启）。"
                "常见原因：① OOM —— 模型显存或主机内存不足，"
                "Linux 容器收到 SIGKILL（exit 137），日志里通常看不到 Python 异常；"
                "② 进程主动退出或宿主机重启。"
                "排查：检查 docker logs 末尾、宿主 dmesg、nvidia-smi 显存占用。"
                "如果是 OOM：换更小的模型（如 voxcpm-0.5b 替代 voxcpm-2）、"
                "降量化精度、或把 device 切回 cpu。点「继续」会原样重试。"
            )
            # finished_at 留空：任务并未真正结束，retry 时会重置
            session.add(j)
        if rows:
            session.commit()
    return len(rows)


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
