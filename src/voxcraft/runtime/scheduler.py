"""全局单任务调度器（ADR-008）。

- 通过 asyncio.Lock 保证任一时刻只执行一个任务
- FIFO 语义由 asyncio.Lock 的公平等待队列提供
- queue_size 暴露排队中（未拿锁）的任务数
- 队列变化时向 EventBus 发 queue_size_changed

cancel(job_id) 接口由 ADR-013 引入。本进程内实现无法打断正在运行的同步
推理（C 扩展阻塞），始终返回 False。真取消能力由 `pool` backend 提供（待实施）。
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from voxcraft.events.bus import Event, EventBus


class Scheduler:
    def __init__(self, bus: EventBus | None = None) -> None:
        self._lock = asyncio.Lock()
        self._active = 0
        self._bus = bus

    @property
    def queue_size(self) -> int:
        return max(0, self._active - 1)

    async def _publish_size(self) -> None:
        if self._bus is None:
            return
        await self._bus.publish(
            Event(type="queue_size_changed", payload={"size": self.queue_size})
        )

    async def run(self, coro_fn: Callable[[], Awaitable[Any]]) -> Any:
        self._active += 1
        await self._publish_size()
        try:
            async with self._lock:
                return await coro_fn()
        finally:
            self._active -= 1
            await self._publish_size()

    async def cancel(self, job_id: str) -> bool:  # noqa: ARG002
        """In-process backend 无法打断运行中的同步推理，统一返回 False。

        真取消由 ADR-013 的 `pool` backend 提供。调用方据返回值决定 UX：
        - False → 不能保证已停；不应向用户展示"已取消"
        - True  → 已真中断，可安全标 cancelled
        """
        return False
