"""产物清理脚本的核心逻辑测试。"""
from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine

from voxcraft.db.models import Job


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("VOXCRAFT_DB", str(tmp_path / "clean.sqlite"))
    from voxcraft.config import get_settings
    from voxcraft.db.engine import get_engine as _get_engine

    get_settings.cache_clear()
    _get_engine.cache_clear()
    eng = _get_engine()
    SQLModel.metadata.create_all(eng)
    yield eng
    get_settings.cache_clear()
    _get_engine.cache_clear()


def _make_job(
    engine,
    *,
    id: str,
    finished_days_ago: int,
    output_path: str | None,
    output_extras: dict | None = None,
):
    finished = datetime.now(UTC) - timedelta(days=finished_days_ago)
    with Session(engine) as s:
        s.add(
            Job(
                id=id,
                kind="tts",
                status="succeeded",
                request={},
                output_path=output_path,
                output_extras=output_extras,
                progress=1.0,
                created_at=finished,
                started_at=finished,
                finished_at=finished,
            )
        )
        s.commit()


def test_cleanup_removes_expired_and_updates_job(engine, tmp_path):
    # 确保 scripts 可 import（不在 sys.path）
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    try:
        import cleanup_outputs
    finally:
        sys.path.pop(0)

    old_file = tmp_path / "old.wav"
    new_file = tmp_path / "new.wav"
    old_file.write_bytes(b"old")
    new_file.write_bytes(b"new")

    _make_job(engine, id="j-old", finished_days_ago=40, output_path=str(old_file))
    _make_job(engine, id="j-new", finished_days_ago=1, output_path=str(new_file))

    rc = cleanup_outputs.cleanup(days=30, dry_run=False)
    assert rc == 0

    assert not old_file.exists()
    assert new_file.exists()

    with Session(engine) as s:
        old_row = s.get(Job, "j-old")
        new_row = s.get(Job, "j-new")
        assert old_row.output_path is None
        assert new_row.output_path == str(new_file)


def test_cleanup_dry_run_does_not_touch(engine, tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    try:
        import cleanup_outputs
    finally:
        sys.path.pop(0)

    f = tmp_path / "keep.wav"
    f.write_bytes(b"data")
    _make_job(engine, id="j", finished_days_ago=100, output_path=str(f))

    cleanup_outputs.cleanup(days=30, dry_run=True)
    assert f.exists()
    with Session(engine) as s:
        assert s.get(Job, "j").output_path == str(f)


def test_cleanup_handles_multi_output_extras(engine, tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    try:
        import cleanup_outputs
    finally:
        sys.path.pop(0)

    v = tmp_path / "v.wav"
    i = tmp_path / "i.wav"
    v.write_bytes(b"v")
    i.write_bytes(b"i")
    _make_job(
        engine,
        id="j-sep",
        finished_days_ago=50,
        output_path=None,
        output_extras={"vocals": str(v), "instrumental": str(i)},
    )

    cleanup_outputs.cleanup(days=30, dry_run=False)

    assert not v.exists()
    assert not i.exists()
    with Session(engine) as s:
        assert s.get(Job, "j-sep").output_extras is None
