#!/usr/bin/env python
"""清理过期的 Job 产物文件，并同步更新 DB（避免 /jobs/:id/output 永远 410）。

用法：
    uv run python scripts/cleanup_outputs.py --days 30         # 删除 30 天前的产物
    uv run python scripts/cleanup_outputs.py --days 7 --dry-run

退出码：0 成功；1 参数错误。
"""
from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlmodel import Session, select

from voxcraft.config import get_settings
from voxcraft.db.engine import get_engine
from voxcraft.db.models import Job


def _collect_paths(job: Job) -> list[Path]:
    paths: list[str] = []
    if job.output_path:
        paths.append(job.output_path)
    if job.output_extras:
        paths.extend(str(v) for v in job.output_extras.values())
    return [Path(p) for p in paths]


def cleanup(days: int, dry_run: bool) -> int:
    threshold = datetime.now(UTC) - timedelta(days=days)
    removed_files = 0
    updated_jobs = 0

    with Session(get_engine()) as session:
        stmt = select(Job).where(Job.finished_at < threshold)  # type: ignore[arg-type]
        expired = session.exec(stmt).all()

        for job in expired:
            dirty = False
            for path in _collect_paths(job):
                if path.exists():
                    if dry_run:
                        print(f"would remove: {path}")
                    else:
                        path.unlink(missing_ok=True)
                    removed_files += 1
                    dirty = True

            if dirty and not dry_run:
                job.output_path = None
                job.output_extras = None
                session.add(job)
                updated_jobs += 1

        if not dry_run and updated_jobs:
            session.commit()

    action = "would clean" if dry_run else "cleaned"
    print(f"{action}: {removed_files} files, {updated_jobs} jobs updated")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="清理过期 Job 产物文件")
    parser.add_argument("--days", type=int, default=30, help="超过 N 天的产物将被删除")
    parser.add_argument("--dry-run", action="store_true", help="仅输出将要执行的动作")
    args = parser.parse_args()

    if args.days < 1:
        print("--days 必须 >= 1", file=sys.stderr)
        return 1

    get_settings()  # trigger env validation
    return cleanup(days=args.days, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
