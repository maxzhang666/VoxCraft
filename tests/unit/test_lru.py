"""LRU=1 模型驻留管理。"""
from __future__ import annotations

import pytest

from voxcraft.providers.mock import (
    InMemoryMockAsrProvider,
    InMemoryMockTtsProvider,
)
from voxcraft.runtime.lru import LruOne


@pytest.fixture
def lru():
    return LruOne()


async def test_ensure_loaded_first_time(lru):
    p = InMemoryMockAsrProvider(name="a", config={})
    await lru.ensure_loaded(p)
    assert p.loaded is True
    assert lru.current is p


async def test_switch_provider_unloads_previous(lru):
    a = InMemoryMockAsrProvider(name="a", config={})
    b = InMemoryMockTtsProvider(name="b", config={})
    await lru.ensure_loaded(a)
    await lru.ensure_loaded(b)
    assert a.loaded is False
    assert b.loaded is True
    assert lru.current is b


async def test_reload_same_provider_is_noop(lru):
    a = InMemoryMockAsrProvider(name="a", config={})
    await lru.ensure_loaded(a)
    # 第二次调用 load() 应幂等：已加载不重复 load
    load_calls = [0]
    original = a.load

    def counting_load():
        load_calls[0] += 1
        original()

    a.load = counting_load  # type: ignore[method-assign]
    await lru.ensure_loaded(a)
    assert load_calls[0] == 0


async def test_evict_unloads_and_clears(lru):
    a = InMemoryMockAsrProvider(name="a", config={})
    await lru.ensure_loaded(a)
    await lru.evict()
    assert a.loaded is False
    assert lru.current is None


async def test_evict_when_empty_is_safe(lru):
    await lru.evict()  # 不应抛异常
    assert lru.current is None
