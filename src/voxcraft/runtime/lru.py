"""LRU=1 模型驻留管理（ADR-008）。

全局单任务前提下，同一时刻只保留一个 Provider 驻留显存。
切换任务时先卸载旧的再加载新的，通过 asyncio.Lock 保证原子性。
加载 / 卸载时向 EventBus 发事件（UI 通过 SSE 感知）。
"""
from __future__ import annotations

import asyncio
from typing import Protocol

from voxcraft.events.bus import Event, EventBus


class _Unloadable(Protocol):
    kind: str
    name: str

    @property
    def loaded(self) -> bool: ...
    def load(self) -> None: ...
    def unload(self) -> None: ...


class LruOne:
    def __init__(self, bus: EventBus | None = None) -> None:
        self._current: _Unloadable | None = None
        self._lock = asyncio.Lock()
        self._bus = bus

    @property
    def current(self) -> _Unloadable | None:
        return self._current

    async def _publish(self, type_: str, target: _Unloadable) -> None:
        if self._bus is None:
            return
        await self._bus.publish(
            Event(type=type_, payload={"kind": target.kind, "name": target.name})
        )

    async def ensure_loaded(self, target: _Unloadable) -> None:
        async with self._lock:
            if self._current is target and target.loaded:
                return
            if self._current is not None and self._current is not target:
                prev = self._current
                prev.unload()
                await self._publish("model_unloaded", prev)
            if not target.loaded:
                await self._publish("model_loading", target)
                target.load()
                await self._publish("model_loaded", target)
            self._current = target

    async def evict(self) -> None:
        async with self._lock:
            if self._current is not None and self._current.loaded:
                prev = self._current
                prev.unload()
                await self._publish("model_unloaded", prev)
            self._current = None
