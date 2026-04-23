"""ModelDownloadService 契约（asyncio.Lock FIFO + SSE + 软取消 + 孤儿清理）。"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from voxcraft.db.models import Model
from voxcraft.events.bus import EventBus


@pytest.fixture
def engine(tmp_path):
    eng = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def models_dir(tmp_path):
    d = tmp_path / "models"
    d.mkdir()
    return d


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def service(engine, bus, models_dir, monkeypatch):
    """服务实例；默认 Mock 所有三个下载分支为可快速完成的 fake。"""
    from voxcraft.models_lib import service as svc_mod

    def _fake_hf(repo_id, local_dir, max_workers=8):
        Path(local_dir).mkdir(parents=True, exist_ok=True)
        (Path(local_dir) / "model.bin").write_bytes(b"x" * 128)
        return Path(local_dir)

    monkeypatch.setattr(svc_mod, "download_hf", _fake_hf)
    monkeypatch.setattr(svc_mod, "download_ms", _fake_hf)
    monkeypatch.setattr(
        svc_mod,
        "download_url",
        lambda url, local_path: (
            Path(local_path).parent.mkdir(parents=True, exist_ok=True),
            Path(local_path).write_bytes(b"y" * 64),
            Path(local_path),
        )[-1],
    )

    return svc_mod.ModelDownloadService(engine=engine, bus=bus, models_dir=models_dir)


# ---------- enqueue / 成功路径 ----------

async def test_enqueue_creates_pending_row_and_runs(service, engine):
    model_id = await service.enqueue(
        catalog_key="whisper-tiny",
        source="hf",
        repo_id="Systran/faster-whisper-tiny",
        kind="asr",
    )
    await service.wait_idle()

    with Session(engine) as s:
        row = s.get(Model, model_id)
        assert row.status == "ready"
        assert row.progress == 1.0
        assert row.local_path is not None
        assert row.size_bytes and row.size_bytes > 0


async def test_success_publishes_completed_event(service, bus, engine):
    q = bus.subscribe()
    await service.enqueue(
        catalog_key="whisper-tiny", source="hf",
        repo_id="x/y", kind="asr",
    )
    await service.wait_idle()

    seen = []
    while not q.empty():
        seen.append(q.get_nowait().type)
    assert "model_download_completed" in seen


# ---------- 失败路径 ----------

async def test_failure_records_error_and_cleans_up(service, engine, monkeypatch):
    from voxcraft.errors import DownloadError
    from voxcraft.models_lib import service as svc_mod

    def _fail(**_):
        raise DownloadError("boom", code="DOWNLOAD_FAILED")

    monkeypatch.setattr(svc_mod, "download_hf", _fail)

    model_id = await service.enqueue(
        catalog_key="whisper-small", source="hf",
        repo_id="x/y", kind="asr",
    )
    await service.wait_idle()

    with Session(engine) as s:
        row = s.get(Model, model_id)
        assert row.status == "failed"
        assert row.error_code == "DOWNLOAD_FAILED"


# ---------- 单任务串行 ----------

async def test_tasks_run_serially(service, engine, monkeypatch):
    from voxcraft.models_lib import service as svc_mod

    order: list[str] = []

    async def _blocking(tag, delay=0.05):
        order.append(f"{tag}-start")
        await asyncio.sleep(delay)
        order.append(f"{tag}-end")

    # 用 side effect 在 event loop 里串行阻塞
    def _fake_hf(repo_id, local_dir, max_workers=8):
        # 此函数在 executor 里跑；用同步 time.sleep 模拟工作
        import time
        order.append(f"{repo_id}-start")
        time.sleep(0.05)
        order.append(f"{repo_id}-end")
        Path(local_dir).mkdir(parents=True, exist_ok=True)
        return Path(local_dir)

    monkeypatch.setattr(svc_mod, "download_hf", _fake_hf)

    ids = []
    for repo in ("A/x", "B/y", "C/z"):
        mid = await service.enqueue(
            catalog_key=f"key-{repo}", source="hf", repo_id=repo, kind="asr",
        )
        ids.append(mid)

    await service.wait_idle()

    # 相邻 start-end 必须成对
    for i in (0, 2, 4):
        assert order[i].endswith("-start")
        assert order[i + 1].endswith("-end")


# ---------- queue_position ----------

async def test_queue_position_reports_sensible(service, engine, monkeypatch):
    from voxcraft.models_lib import service as svc_mod

    gate = asyncio.Event()

    def _blocking(repo_id, local_dir, max_workers=8):
        # executor 线程里等待 gate；需用非 asyncio 机制
        import time
        while not gate.is_set():
            time.sleep(0.01)
        Path(local_dir).mkdir(parents=True, exist_ok=True)
        return Path(local_dir)

    monkeypatch.setattr(svc_mod, "download_hf", _blocking)

    m1 = await service.enqueue(catalog_key="a", source="hf", repo_id="a/a", kind="asr")
    m2 = await service.enqueue(catalog_key="b", source="hf", repo_id="b/b", kind="asr")
    m3 = await service.enqueue(catalog_key="c", source="hf", repo_id="c/c", kind="asr")

    await asyncio.sleep(0.05)  # 让 m1 进入锁
    assert service.queue_position(m1) == 0   # 正在跑
    assert service.queue_position(m2) == 1
    assert service.queue_position(m3) == 2

    gate.set()
    await service.wait_idle()
    assert service.queue_position(m1) is None


# ---------- 软取消 ----------

async def test_cancel_waiting_task_marks_cancelled(service, engine, monkeypatch):
    from voxcraft.models_lib import service as svc_mod

    gate = asyncio.Event()

    def _blocking(repo_id, local_dir, max_workers=8):
        import time
        while not gate.is_set():
            time.sleep(0.01)
        Path(local_dir).mkdir(parents=True, exist_ok=True)
        return Path(local_dir)

    monkeypatch.setattr(svc_mod, "download_hf", _blocking)

    m1 = await service.enqueue(catalog_key="a", source="hf", repo_id="a/a", kind="asr")
    m2 = await service.enqueue(catalog_key="b", source="hf", repo_id="b/b", kind="asr")

    await asyncio.sleep(0.05)
    await service.cancel(m2)   # 还在等待

    with Session(engine) as s:
        assert s.get(Model, m2).status == "cancelled"

    gate.set()
    await service.wait_idle()
    with Session(engine) as s:
        assert s.get(Model, m1).status == "ready"
        assert s.get(Model, m2).status == "cancelled"   # 仍保持


# ---------- 启动孤儿清理 ----------

def test_startup_cleanup_resets_orphan_downloading(engine, models_dir, bus):
    """服务启动时扫描 status=downloading 的僵尸行 → 改 failed + 删半成品。"""
    from voxcraft.models_lib import service as svc_mod

    # 造孤儿：DB 有 downloading 行 + 磁盘有半成品目录
    orphan_dir = models_dir / "orphan"
    orphan_dir.mkdir()
    (orphan_dir / "half.bin").write_bytes(b"half")

    with Session(engine) as s:
        s.add(Model(
            catalog_key="orphan-x",
            source="hf",
            repo_id="x/y",
            kind="asr",
            status="downloading",
            progress=0.3,
            local_path=str(orphan_dir),
        ))
        s.commit()

    s = svc_mod.ModelDownloadService(engine=engine, bus=bus, models_dir=models_dir)
    s.startup_cleanup()

    with Session(engine) as sess:
        row = sess.exec(select(Model).where(Model.catalog_key == "orphan-x")).first()
        assert row.status == "failed"
        assert row.error_code == "ORPHAN_ON_STARTUP"
    assert not orphan_dir.exists()
