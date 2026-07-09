"""Terminal events WebSocket — pushes terminal lifecycle events to dashboards."""

from __future__ import annotations

import asyncio
from platform.core.logging import get_logger
from platform.events.bus import get_event_bus
from platform.events.topics import Topic

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["ws"])
_log = get_logger(__name__)


@router.websocket("/terminal-events")
async def terminal_events_ws(ws: WebSocket) -> None:
    token = ws.query_params.get("token")
    if not token:
        await ws.close(code=4401, reason="Missing token")
        return
    try:
        from platform.core.security import decode_token

        decode_token(token)
    except Exception:
        await ws.close(code=4401, reason="Bad token")
        return

    await ws.accept()
    queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=200)

    async def handler(payload: dict) -> None:
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass

    bus = get_event_bus()
    bus.subscribe(Topic.TERMINAL_EVENTS, handler)
    bus.subscribe(Topic.EXECUTION_REPORTS, handler)
    bus.subscribe(Topic.RISK_EVENTS, handler)

    try:
        while True:
            payload = await asyncio.wait_for(queue.get(), timeout=30)
            await ws.send_json(payload)
    except TimeoutError:
        await ws.send_json({"type": "ping"})
    except WebSocketDisconnect:
        pass
    finally:
        for t in (Topic.TERMINAL_EVENTS, Topic.EXECUTION_REPORTS, Topic.RISK_EVENTS):
            if handler in bus._handlers.get(t, []):
                bus._handlers[t].remove(handler)
