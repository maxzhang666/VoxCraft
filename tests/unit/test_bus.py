"""EventBus 发布订阅契约。"""
from __future__ import annotations

import asyncio

import pytest

from voxcraft.events.bus import Event, EventBus


@pytest.fixture
def bus():
    return EventBus()


async def test_publish_delivers_to_subscriber(bus):
    q = bus.subscribe()
    await bus.publish(Event(type="job_progress", payload={"id": "x", "progress": 0.5}))
    ev = await asyncio.wait_for(q.get(), timeout=0.5)
    assert ev.type == "job_progress"
    assert ev.payload == {"id": "x", "progress": 0.5}


async def test_multiple_subscribers_receive_each_event(bus):
    q1 = bus.subscribe()
    q2 = bus.subscribe()
    await bus.publish(Event(type="test"))
    for q in (q1, q2):
        ev = await asyncio.wait_for(q.get(), timeout=0.5)
        assert ev.type == "test"


async def test_unsubscribe_stops_delivery(bus):
    q = bus.subscribe()
    bus.unsubscribe(q)
    await bus.publish(Event(type="test"))
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(q.get(), timeout=0.1)


async def test_full_queue_drops_instead_of_blocking(bus):
    q = bus.subscribe(maxsize=2)
    await bus.publish(Event(type="a"))
    await bus.publish(Event(type="b"))
    # 第三条应被丢弃，不阻塞
    await asyncio.wait_for(bus.publish(Event(type="c")), timeout=0.2)
    assert q.qsize() == 2
