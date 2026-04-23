"""/admin/events SSE 事件流。"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from voxcraft.events.bus import get_bus


router = APIRouter(prefix="/admin/events", tags=["admin"])

_PING_INTERVAL = 30.0  # 秒，超时心跳防代理/浏览器断开


@router.get("")
async def events(request: Request):
    bus = get_bus()
    queue = bus.subscribe(maxsize=1000)

    async def generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=_PING_INTERVAL)
                    yield {
                        "data": json.dumps({
                            "type": ev.type,
                            "payload": ev.payload,
                            "ts": ev.ts.isoformat(),
                        })
                    }
                except asyncio.TimeoutError:
                    yield {"data": json.dumps({"type": "ping"})}
        finally:
            bus.unsubscribe(queue)

    return EventSourceResponse(generator())
