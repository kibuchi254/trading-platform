"""Bridge client — used by the REST API & application layer to talk to terminals.

The application layer NEVER opens a WebSocket itself; it always goes through
this client. This keeps the indirection in one place, so we can later swap
WebSocket for gRPC / AMQP / FIX without touching use-case code.
"""
from __future__ import annotations

import uuid
from typing import Any

from platform.core.exceptions import TerminalOffline
from platform.core.logging import get_logger
from platform.infrastructure.mt5_bridge.command_queue import get_command_queue
from platform.infrastructure.mt5_bridge.protocol import (
    BridgeMessage, CommandType, PlaceOrderPayload, command,
)
from platform.infrastructure.mt5_bridge.registry import get_registry

_log = get_logger(__name__)


class BridgeClient:
    """High-level operations the application layer calls."""

    async def place_order(
        self,
        *,
        terminal_id: str,
        symbol: str,
        side: str,
        order_type: str,
        volume: float,
        price: float | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        client_order_id: str | None = None,
        comment: str | None = None,
        magic: int | None = None,
        timeout: float = 10.0,
    ) -> BridgeMessage:
        registry = get_registry()
        rec = await registry.require(terminal_id)

        payload = PlaceOrderPayload(
            client_order_id=client_order_id or f"atlas-{uuid.uuid4().hex[:12]}",
            symbol=symbol, side=side, order_type=order_type, volume=volume,
            price=price, stop_loss=stop_loss, take_profit=take_profit,
            comment=comment, magic=magic,
        ).model_dump(mode="json")
        # Make timestamps JSON-serializable
        cmd = command(CommandType.PLACE_ORDER, terminal_id=terminal_id, payload=payload)
        await rec.session.send(cmd)
        return await get_command_queue().enqueue(cmd, timeout=timeout)

    async def cancel_order(
        self, *, terminal_id: str, broker_order_id: str, timeout: float = 10.0
    ) -> BridgeMessage:
        registry = get_registry()
        rec = await registry.require(terminal_id)
        cmd = command(
            CommandType.CANCEL_ORDER,
            terminal_id=terminal_id,
            payload={"broker_order_id": broker_order_id},
        )
        await rec.session.send(cmd)
        return await get_command_queue().enqueue(cmd, timeout=timeout)

    async def close_position(
        self, *, terminal_id: str, broker_position_id: str, volume: float | None = None, timeout: float = 10.0
    ) -> BridgeMessage:
        registry = get_registry()
        rec = await registry.require(terminal_id)
        cmd = command(
            CommandType.CLOSE_POSITION,
            terminal_id=terminal_id,
            payload={"broker_position_id": broker_position_id, "volume": volume},
        )
        await rec.session.send(cmd)
        return await get_command_queue().enqueue(cmd, timeout=timeout)

    async def sync_positions(self, *, terminal_id: str, timeout: float = 30.0) -> BridgeMessage:
        registry = get_registry()
        rec = await registry.require(terminal_id)
        cmd = command(CommandType.SYNC_POSITIONS, terminal_id=terminal_id)
        await rec.session.send(cmd)
        return await get_command_queue().enqueue(cmd, timeout=timeout)

    async def sync_account(self, *, terminal_id: str, timeout: float = 10.0) -> BridgeMessage:
        registry = get_registry()
        rec = await registry.require(terminal_id)
        cmd = command(CommandType.SYNC_ACCOUNT, terminal_id=terminal_id)
        await rec.session.send(cmd)
        return await get_command_queue().enqueue(cmd, timeout=timeout)

    async def subscribe_ticks(
        self, *, terminal_id: str, symbols: list[str], timeout: float = 5.0
    ) -> BridgeMessage:
        registry = get_registry()
        rec = await registry.require(terminal_id)
        cmd = command(
            CommandType.SUBSCRIBE_TICKS, terminal_id=terminal_id, payload={"symbols": symbols}
        )
        await rec.session.send(cmd)
        return await get_command_queue().enqueue(cmd, timeout=timeout)


_client: BridgeClient | None = None


def get_bridge_client() -> BridgeClient:
    global _client
    if _client is None:
        _client = BridgeClient()
    return _client
