"""进程内事件总线（SSE 上游）。

- 生产者：Runtime 层（任务进度、模型加载状态等）
- 消费者：SSE `/admin/events` 端点（每个 HTTP 连接一个 subscriber queue）
- 慢订阅者队列满时丢弃新事件（防反压阻塞发布）
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class Event:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    ts: datetime = field(default_factory=lambda: datetime.now(UTC))


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[Event]] = []

    def subscribe(self, maxsize: int = 1000) -> asyncio.Queue[Event]:
        q: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Event]) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    async def publish(self, event: Event) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # 慢订阅者丢弃


_bus: EventBus | None = None


def get_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
