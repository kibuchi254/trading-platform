"""BridgeSession — one instance per connected terminal WebSocket.

Wraps the raw WebSocket connection and provides:
- typed message send/receive
- backpressure handling
- graceful close
"""

from __future__ import annotations

import asyncio
import uuid
from platform.core.logging import get_logger
from platform.infrastructure.mt5_bridge.protocol import BridgeMessage
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from websockets.asyncio.server import ServerConnection

_log = get_logger(__name__)


class BridgeSession:
    """One per WebSocket connection. Identified by `id` (server-assigned)
    until the terminal registers with its own `terminal_id`."""

    def __init__(self, ws: ServerConnection) -> None:
        self.id: str = str(uuid.uuid4())
        self.ws = ws
        self.terminal_id: str | None = None  # set after REGISTER
        self._send_lock = asyncio.Lock()
        self._closed = False

    async def send(self, msg: BridgeMessage) -> None:
        if self._closed:
            raise RuntimeError("Session closed")
        payload = msg.model_dump_json()
        async with self._send_lock:
            await self.ws.send(payload)

    async def recv(self) -> BridgeMessage:
        raw = await self.ws.recv()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return BridgeMessage.model_validate_json(raw)

    async def close(self, *, code: int = 1000, reason: str = "normal") -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self.ws.close(code=code, reason=reason)
        except Exception:
            pass
        _log.info(
            "session_closed",
            session_id=self.id,
            terminal_id=self.terminal_id,
            code=code,
            reason=reason,
        )
