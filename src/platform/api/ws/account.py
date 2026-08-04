"""Account WebSocket — streams live MT5 account state to dashboards.

Subscribes to the `ACCOUNT_UPDATES` event topic (published by the bridge
`handle_account_update` handler when a terminal pushes `evt.account.update`).
Clients seed the initial snapshot via `POST /api/v1/terminals/{id}/sync-account`
and then receive live balance/equity/margin updates over this socket.
"""

from __future__ import annotations

import asyncio
import contextlib
from platform.core.logging import get_logger
from platform.events.bus import get_event_bus
from platform.events.topics import Topic

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["ws"])
_log = get_logger(__name__)


@router.websocket("/account")
async def account_ws(ws: WebSocket) -> None:
    """Auth via query param `?token=<jwt>` (WebSocket can't set headers)."""
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

    # Optional scoping: ?terminal_id=<id> filters to one terminal.
    terminal_id = ws.query_params.get("terminal_id")
    queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=200)

    async def handler(payload: dict) -> None:
        if terminal_id and payload.get("terminal_id") != terminal_id:
            return
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait(payload)

    bus = get_event_bus()
    bus.subscribe(Topic.ACCOUNT_UPDATES, handler)

    try:
        while True:
            payload = await asyncio.wait_for(queue.get(), timeout=30)
            await ws.send_json({"type": "account", **payload})
    except TimeoutError:
        await ws.send_json({"type": "ping"})
    except WebSocketDisconnect:
        pass
    except Exception:
        _log.exception("account_ws_error")
    finally:
        if handler in bus._handlers.get(Topic.ACCOUNT_UPDATES, []):
            bus._handlers[Topic.ACCOUNT_UPDATES].remove(handler)
