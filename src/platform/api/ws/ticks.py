"""Ticks WebSocket router — streams live ticks to clients."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from platform.core.dependencies import get_current_user
from platform.core.logging import get_logger
from platform.events.bus import get_event_bus
from platform.events.topics import Topic

router = APIRouter(tags=["ws"])
_log = get_logger(__name__)


class TickSub(BaseModel):
    symbols: list[str] = []


@router.websocket("/ticks")
async def ticks_ws(ws: WebSocket) -> None:
    """Auth via query param `?token=<jwt>` — WebSocket can't set headers easily."""
    token = ws.query_params.get("token")
    if not token:
        await ws.close(code=4401, reason="Missing token")
        return
    try:
        from platform.core.security import decode_token
        claims = decode_token(token)
    except Exception:
        await ws.close(code=4401, reason="Bad token")
        return

    await ws.accept()
    sub_msg = await ws.receive_text()
    try:
        sub = TickSub(**json.loads(sub_msg))
    except Exception as e:
        await ws.close(code=4400, reason=f"Bad subscription: {e}")
        return

    symbols = set(sub.symbols)
    queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=1000)

    async def handler(payload: dict) -> None:
        if symbols and payload.get("symbol") not in symbols:
            return
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass  # drop on backpressure

    bus = get_event_bus()
    bus.subscribe(Topic.TICKS, handler)

    try:
        while True:
            payload = await asyncio.wait_for(queue.get(), timeout=30)
            await ws.send_json({"type": "tick", **payload})
    except asyncio.TimeoutError:
        await ws.send_json({"type": "ping"})
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        _log.exception("ticks_ws_error")
    finally:
        bus._handlers[Topic.TICKS].remove(handler)
