"""Stale job interruption + manual retry path."""
from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from voxcraft.db.bootstrap import mark_stale_jobs_interrupted
from voxcraft.db.models import Job


@pytest.fixture
def engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'test.sqlite'}")
    SQLModel.metadata.create_all(eng)
    return eng


def _seed(engine, *, status: str, job_id: str = "j1", kind: str = "tts") -> None:
    with Session(engine) as s:
        s.add(Job(id=job_id, kind=kind, status=status, request={}, progress=0.0))
        s.commit()


def test_mark_running_jobs_interrupted(engine):
    _seed(engine, status="running", job_id="r1")
    _seed(engine, status="pending", job_id="p1")
    _seed(engine, status="succeeded", job_id="s1")
    _seed(engine, status="failed", job_id="f1")

    n = mark_stale_jobs_interrupted(engine)
    assert n == 2  # running + pending → interrupted

    with Session(engine) as s:
        rows = {j.id: j for j in s.exec(select(Job)).all()}
    assert rows["r1"].status == "interrupted"
    assert rows["p1"].status == "interrupted"
    assert rows["s1"].status == "succeeded"  # 终态保持
    assert rows["f1"].status == "failed"
    assert rows["r1"].error_code == "INTERRUPTED"
    assert "继续" in (rows["r1"].error_message or "")


def test_mark_stale_idempotent(engine):
    """没有 running/pending → 0；二次调用也是 0。"""
    assert mark_stale_jobs_interrupted(engine) == 0
    _seed(engine, status="running")
    assert mark_stale_jobs_interrupted(engine) == 1
    assert mark_stale_jobs_interrupted(engine) == 0  # 已经被改成 interrupted，不再触发


def test_retry_endpoint_accepts_interrupted(client, mock_all_registered):
    """interrupted 走 retry 端点应放行（与 failed/cancelled 一致）。"""
    # 直接在 DB 注入一个 interrupted Job 模拟系统刚重启完的现场——
    # 不走 /api/tts 路径，避免 worker 异步覆盖 status
    from sqlmodel import Session as _S
    from voxcraft.db.engine import get_engine
    with _S(get_engine()) as s:
        s.add(Job(
            id="interrupted-job-1",
            kind="tts",
            status="interrupted",
            request={"text": "hi", "voice_id": "x"},
            progress=0.5,
            error_code="INTERRUPTED",
            error_message="restart",
        ))
        s.commit()

    r = client.post("/api/jobs/interrupted-job-1/retry")
    assert r.status_code == 202, r.text
    assert r.json()["job_id"] == "interrupted-job-1"
    assert r.json()["status"] == "pending"
