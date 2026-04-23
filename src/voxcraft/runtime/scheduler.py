"""In-process Scheduler 实现（ADR-008 + ADR-013 接口）。

- submit(JobRequest) → 在主进程事件循环里通过 asyncio.to_thread 跑同步 runner
- cancel(job_id) 永远返回 False：in-process 下无法打断正在执行的 C 扩展阻塞调用
- run(coro_fn) 保留为兼容 API（当前代码路径仍在用；后续可迁到 submit）
- 所有任务走单个 asyncio.Lock 串行；FIFO 由 Lock 的公平等待保证
- 每次 active 变化发 queue_size_changed 事件

真取消能力由 `PoolScheduler` 提供（ADR-013）。
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from voxcraft.events.bus import Event, EventBus
from voxcraft.runtime.scheduler_api import JobRequest, JobResult
from voxcraft.runtime.worker_runners import _LruOne, run as run_sync


class InProcessScheduler:
    def __init__(self, bus: EventBus | None = None) -> None:
        self._lock = asyncio.Lock()
        self._active = 0
        self._bus = bus
        self._lru = _LruOne()

    @property
    def queue_size(self) -> int:
        return max(0, self._active - 1)

    async def _publish_size(self) -> None:
        if self._bus is None:
            return
        await self._bus.publish(
            Event(type="queue_size_changed", payload={"size": self.queue_size})
        )

    async def submit(self, req: JobRequest) -> JobResult:
        """新接口（ADR-013）：提交 JobRequest，worker_runners 同步执行，返回 JobResult。"""
        self._active += 1
        await self._publish_size()
        try:
            async with self._lock:
                return await asyncio.to_thread(run_sync, req, self._lru)
        finally:
            self._active -= 1
            await self._publish_size()

    async def run(self, coro_fn: Callable[[], Awaitable[Any]]) -> Any:
        """兼容 API：直接跑一个协程工厂。新代码应改用 submit。"""
        self._active += 1
        await self._publish_size()
        try:
            async with self._lock:
                return await coro_fn()
        finally:
            self._active -= 1
            await self._publish_size()

    async def cancel(self, job_id: str) -> bool:  # noqa: ARG002
        """In-process 后端无法打断运行中的同步推理；统一返回 False。

        真取消由 ADR-013 的 `PoolScheduler` 提供。调用方据返回值决定 UX。
        """
        return False

    async def shutdown(self) -> None:
        """In-process 后端无资源需释放；LRU 的 unload 走进程退出即可。"""
        self._lru.evict()


# 向后兼容旧名字（现有代码 import Scheduler）
Scheduler = InProcessScheduler
