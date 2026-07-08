"""Flatten everything on a terminal — close all positions, cancel all orders.

Vertical slice:

  API → command → load open Positions + pending Orders for the terminal
        → bridge FLATTEN_ALL command (single round-trip)
        → mark every Position closed, every Order cancelled
        → publish RISK_EVENTS + TERMINAL_EVENTS

This is the "emergency button" — typically invoked by an operator after a
kill-switch engagement (see :mod:`platform.application.commands.engage_kill_switch`)
to bring every position flat on a specific terminal.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select

from platform.core.exceptions import NotFoundError
from platform.core.logging import get_logger
from platform.db.models import Order as OrderModel, Position, Terminal
from platform.db.session import db_context
from platform.events.bus import get_event_bus
from platform.events.topics import Topic
from platform.infrastructure.mt5_bridge.command_queue import get_command_queue
from platform.infrastructure.mt5_bridge.protocol import CommandType, command
from platform.infrastructure.mt5_bridge.registry import get_registry

_log = get_logger(__name__)

_PENDING_ORDER_STATUSES = frozenset({"pending", "submitted", "partial"})


# ── Command + DTO ──────────────────────────────────────────────────────────


class FlattenAllCommand(BaseModel):
    org_id: UUID
    user_id: UUID
    terminal_id: str  # external
    reason: str = "manual"


class FlattenAllResult(BaseModel):
    terminal_id: str
    positions_closed: int
    orders_cancelled: int
    flattened_at: str


# ── Handler ─────────────────────────────────────────────────────────────────


async def handle_flatten_all(cmd: FlattenAllCommand) -> FlattenAllResult:
    """Send FLATTEN_ALL to the terminal and reconcile the DB rows."""
    registry = get_registry()
    rec = await registry.require(cmd.terminal_id)
    cmd_msg = command(
        CommandType.FLATTEN_ALL,
        terminal_id=cmd.terminal_id,
        payload={"reason": cmd.reason},
    )
    await rec.session.send(cmd_msg)
    await get_command_queue().enqueue(cmd_msg, timeout=30.0)

    now = datetime.now(timezone.utc)
    positions_closed = 0
    orders_cancelled = 0

    async with db_context() as db:
        terminal = (
            await db.execute(
                select(Terminal).where(
                    Terminal.terminal_id == cmd.terminal_id, Terminal.org_id == cmd.org_id
                )
            )
        ).scalar_one_or_none()
        if terminal is None:
            raise NotFoundError(f"Terminal {cmd.terminal_id} not found")

        # Close all open positions for this terminal.
        open_positions = (
            await db.execute(
                select(Position).where(
                    Position.terminal_id == terminal.id, Position.status == "open"
                )
            )
        ).scalars().all()
        for pos in open_positions:
            pos.status = "closed"
            pos.closed_at = now
            # Realized PnL is unknown without a fill ack — leave the existing
            # ``realized_pnl`` (mark-to-market value) untouched. The Trade
            # rows will be written by the close-position event handler when
            # the terminal emits POSITION_CLOSED events.
            positions_closed += 1

        # Cancel every still-pending order.
        pending_orders = (
            await db.execute(
                select(OrderModel).where(
                    OrderModel.terminal_id == terminal.id,
                    OrderModel.status.in_(_PENDING_ORDER_STATUSES),
                )
            )
        ).scalars().all()
        for order in pending_orders:
            order.status = "cancelled"
            order.rejection_reason = f"flatten_all: {cmd.reason}"
            order.updated_at = now
            orders_cancelled += 1

        await db.commit()

    await get_event_bus().publish(
        Topic.RISK_EVENTS,
        {
            "type": "flatten_all_executed",
            "org_id": str(cmd.org_id),
            "rule": "flatten_all",
            "severity": "critical",
            "action": "close_all",
            "details": {
                "terminal_id": cmd.terminal_id,
                "reason": cmd.reason,
                "positions_closed": positions_closed,
                "orders_cancelled": orders_cancelled,
                "actor_id": str(cmd.user_id),
            },
        },
    )
    await get_event_bus().publish(
        Topic.TERMINAL_EVENTS,
        {
            "type": "terminal_flattened",
            "org_id": str(cmd.org_id),
            "terminal_id": cmd.terminal_id,
            "positions_closed": positions_closed,
            "orders_cancelled": orders_cancelled,
            "reason": cmd.reason,
        },
    )
    _log.warning(
        "flatten_all_executed",
        org_id=str(cmd.org_id),
        terminal_id=cmd.terminal_id,
        positions_closed=positions_closed,
        orders_cancelled=orders_cancelled,
        reason=cmd.reason,
    )
    return FlattenAllResult(
        terminal_id=cmd.terminal_id,
        positions_closed=positions_closed,
        orders_cancelled=orders_cancelled,
        flattened_at=now.isoformat(),
    )
