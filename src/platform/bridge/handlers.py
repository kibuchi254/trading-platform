"""Bridge message handlers — process incoming events from MT5 terminals.

Each handler takes a BridgeMessage and the session it arrived on. Handlers
must be fast: they offload persistence to a worker pool via the event bus.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from platform.core.logging import get_logger
from platform.events.bus import get_event_bus
from platform.events.topics import Topic
from platform.infrastructure.mt5_bridge.command_queue import get_command_queue
from platform.infrastructure.mt5_bridge.protocol import (
    AccountUpdatePayload, BridgeMessage, EventType, ExecutionReportPayload,
    HeartbeatPayload, PositionUpdatePayload, RegisterPayload, TickPayload,
)
from platform.infrastructure.mt5_bridge.registry import TerminalRecord, get_registry

if TYPE_CHECKING:
    from platform.bridge.session import BridgeSession

_log = get_logger(__name__)


async def handle_register(msg: BridgeMessage, session: "BridgeSession") -> None:
    payload = RegisterPayload(**msg.payload)
    from platform.core.config import get_settings
    settings = get_settings()
    if payload.auth_token != settings.bridge_auth_token.get_secret_value():
        _log.warning("register_bad_token", terminal_id=payload.terminal_id)
        await session.close(code=4003, reason="bad auth token")
        return

    record = TerminalRecord(
        terminal_id=payload.terminal_id,
        broker=payload.broker,
        account=payload.account,
        version=payload.version,
        symbols=payload.symbols,
        capabilities=payload.capabilities,
        session=session,
    )
    registry = get_registry()
    await registry.register(record)
    session.terminal_id = payload.terminal_id

    bus = get_event_bus()
    await bus.publish(
        Topic.TERMINAL_EVENTS,
        {"type": "terminal_registered", "terminal_id": payload.terminal_id, "broker": payload.broker},
    )


async def handle_heartbeat(msg: BridgeMessage, session: "BridgeSession") -> None:
    payload = HeartbeatPayload(**msg.payload)
    registry = get_registry()
    await registry.heartbeat(payload.terminal_id)


async def handle_tick(msg: BridgeMessage, session: "BridgeSession") -> None:
    payload = TickPayload(**msg.payload)
    bus = get_event_bus()
    # Ticks are hot — fan out to subscribers (market data engine, strategies, AI)
    await bus.publish(
        Topic.TICKS,
        {
            "terminal_id": msg.terminal_id,
            "symbol": payload.symbol,
            "bid": payload.bid,
            "ask": payload.ask,
            "last": payload.last,
            "volume": payload.volume,
            "ts": payload.ts.isoformat(),
        },
    )


async def handle_execution_report(msg: BridgeMessage, session: "BridgeSession") -> None:
    """Terminal reports an order state change.

    Resolves the pending command (if any) AND publishes a domain event
    so the application layer can update the Order/Position aggregates.
    """
    payload = ExecutionReportPayload(**msg.payload)
    queue = get_command_queue()
    if msg.reply_to:
        await queue.resolve(msg.terminal_id or "", msg.reply_to, msg)
    bus = get_event_bus()
    await bus.publish(
        Topic.EXECUTION_REPORTS,
        {
            "terminal_id": msg.terminal_id,
            "client_order_id": payload.client_order_id,
            "broker_order_id": payload.broker_order_id,
            "broker_execution_id": payload.broker_execution_id,
            "status": payload.status,
            "filled_volume": payload.filled_volume,
            "avg_price": payload.avg_price,
            "rejection_reason": payload.rejection_reason,
            "executed_at": payload.executed_at.isoformat(),
        },
    )


async def handle_position_update(msg: BridgeMessage, session: "BridgeSession") -> None:
    payload = PositionUpdatePayload(**msg.payload)
    bus = get_event_bus()
    await bus.publish(
        Topic.POSITION_UPDATES,
        {
            "terminal_id": msg.terminal_id,
            "broker_position_id": payload.broker_position_id,
            "symbol": payload.symbol,
            "side": payload.side,
            "volume": payload.volume,
            "open_price": payload.open_price,
            "current_price": payload.current_price,
            "stop_loss": payload.stop_loss,
            "take_profit": payload.take_profit,
            "swap": payload.swap,
            "unrealized_pnl": payload.unrealized_pnl,
            "opened_at": payload.opened_at.isoformat(),
        },
    )


async def handle_account_update(msg: BridgeMessage, session: "BridgeSession") -> None:
    payload = AccountUpdatePayload(**msg.payload)
    bus = get_event_bus()
    await bus.publish(
        Topic.ACCOUNT_UPDATES,
        {
            "terminal_id": msg.terminal_id,
            "balance": payload.balance,
            "equity": payload.equity,
            "margin": payload.margin,
            "free_margin": payload.free_margin,
            "currency": payload.currency,
            "leverage": payload.leverage,
        },
    )


async def handle_error(msg: BridgeMessage, session: "BridgeSession") -> None:
    _log.error("terminal_error", terminal_id=msg.terminal_id, payload=msg.payload)


# ── Dispatch table ──────────────────────────────────────────────────────────
HANDLERS: dict[str, callable] = {  # type: ignore[type-arg]
    EventType.REGISTER.value: handle_register,
    EventType.HEARTBEAT.value: handle_heartbeat,
    EventType.TICK.value: handle_tick,
    EventType.ORDER_ACCEPTED.value: handle_execution_report,
    EventType.ORDER_REJECTED.value: handle_execution_report,
    EventType.ORDER_PARTIAL.value: handle_execution_report,
    EventType.ORDER_FILLED.value: handle_execution_report,
    EventType.ORDER_CANCELLED.value: handle_execution_report,
    EventType.POSITION_OPENED.value: handle_position_update,
    EventType.POSITION_MODIFIED.value: handle_position_update,
    EventType.POSITION_CLOSED.value: handle_position_update,
    EventType.ACCOUNT_UPDATE.value: handle_account_update,
    EventType.ERROR.value: handle_error,
}


async def dispatch(msg: BridgeMessage, session: "BridgeSession") -> None:
    handler = HANDLERS.get(msg.t)
    if handler is None:
        _log.warning("no_handler_for_event", type=msg.t, terminal_id=msg.terminal_id)
        return
    try:
        await handler(msg, session)
    except Exception:  # noqa: BLE001
        _log.exception("handler_error", type=msg.t, terminal_id=msg.terminal_id)
