"""全局单任务调度器契约。"""
from __future__ import annotations

import asyncio

import pytest

from voxcraft.runtime.scheduler import Scheduler


async def test_single_task_returns_value():
    s = Scheduler()
    result = await s.run(lambda: _echo("hello"))
    assert result == "hello"


async def test_tasks_run_serially_no_interleave():
    s = Scheduler()
    order: list[str] = []

    async def task(name: str) -> str:
        order.append(f"{name}-start")
        await asyncio.sleep(0.02)
        order.append(f"{name}-end")
        return name

    results = await asyncio.gather(
        s.run(lambda: task("A")),
        s.run(lambda: task("B")),
        s.run(lambda: task("C")),
    )
    assert set(results) == {"A", "B", "C"}
    # 相邻 start-end 成对（不交错）
    for i in (0, 2, 4):
        assert order[i].endswith("-start")
        assert order[i + 1].endswith("-end")
        assert order[i][0] == order[i + 1][0]


async def test_exception_releases_lock():
    s = Scheduler()

    async def bad():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await s.run(lambda: bad())

    # 第二个任务应能正常获取锁
    result = await s.run(lambda: _echo("recovered"))
    assert result == "recovered"


async def test_queue_size_reports_pending():
    s = Scheduler()
    gate = asyncio.Event()

    async def blocking():
        await gate.wait()
        return "done"

    t1 = asyncio.create_task(s.run(lambda: blocking()))
    t2 = asyncio.create_task(s.run(lambda: blocking()))
    t3 = asyncio.create_task(s.run(lambda: blocking()))

    # 让调度循环进入
    await asyncio.sleep(0.05)
    # 1 个在跑，2 个等待
    assert s.queue_size == 2

    gate.set()
    await asyncio.gather(t1, t2, t3)
    assert s.queue_size == 0


async def _echo(v):
    return v
