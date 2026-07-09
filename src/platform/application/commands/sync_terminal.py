"""Force a full terminal sync — positions + account + pending orders.

Vertical slice:

  API → command → delegate to handle_sync_positions + handle_sync_account
        (+ send raw SYNC_ORDERS command) → update Terminal.last_synced_at
        → publish TERMINAL_EVENTS event

The position/account reconciliation logic already lives in
:mod:`platform.application.commands.sync_positions` and
:mod:`platform.application.commands.sync_account`; this handler just
orchestrates them (plus the orders sync, which has no dedicated command)
and updates the terminal row.
"""

from __future__ import annotations

from datetime import UTC, datetime
from platform.application.commands.sync_account import SyncAccountCommand, handle_sync_account
from platform.application.commands.sync_positions import (
    SyncPositionsCommand,
    handle_sync_positions,
)
from platform.core.exceptions import NotFoundError
from platform.core.logging import get_logger
from platform.db.models import Terminal
from platform.db.session import db_context
from platform.events.bus import get_event_bus
from platform.events.topics import Topic
from platform.infrastructure.mt5_bridge.command_queue import get_command_queue
from platform.infrastructure.mt5_bridge.protocol import CommandType, command
from platform.infrastructure.mt5_bridge.registry import get_registry
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select

_log = get_logger(__name__)
SyncType = Literal["all", "positions", "account", "orders"]


# ── Command + DTO ──────────────────────────────────────────────────────────


class SyncTerminalCommand(BaseModel):
    org_id: UUID
    user_id: UUID
    terminal_id: str
    sync_type: SyncType = "all"


class SyncTerminalResult(BaseModel):
    terminal_id: str
    synced_positions: int = 0
    closed_positions: int = 0
    account_synced: bool = False
    synced_orders: int = 0
    last_synced_at: str


# ── Handler ─────────────────────────────────────────────────────────────────


async def handle_sync_terminal(cmd: SyncTerminalCommand) -> SyncTerminalResult:
    """Run the requested sync subset and store results in DB."""
    now = datetime.now(UTC)
    synced_positions = closed_positions = synced_orders = 0
    account_synced = False

    if cmd.sync_type in ("all", "positions"):
        pos_res = await handle_sync_positions(
            SyncPositionsCommand(
                org_id=cmd.org_id, user_id=cmd.user_id, terminal_id=cmd.terminal_id
            )
        )
        synced_positions = pos_res.synced_count
        closed_positions = pos_res.closed_count

    if cmd.sync_type in ("all", "account"):
        await handle_sync_account(
            SyncAccountCommand(org_id=cmd.org_id, user_id=cmd.user_id, terminal_id=cmd.terminal_id)
        )
        account_synced = True

    if cmd.sync_type in ("all", "orders"):
        # The bridge client has no high-level sync_orders method; send the
        # raw SYNC_ORDERS command via the command queue.
        rec = await get_registry().require(cmd.terminal_id)
        cmd_msg = command(CommandType.SYNC_ORDERS, terminal_id=cmd.terminal_id)
        await rec.session.send(cmd_msg)
        reply = await get_command_queue().enqueue(cmd_msg, timeout=30.0)
        synced_orders = len(reply.payload.get("orders", []) or [])

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
        terminal.last_heartbeat_at = now
        terminal.updated_at = now
        await db.commit()

    await get_event_bus().publish(
        Topic.TERMINAL_EVENTS,
        {
            "type": "terminal_synced",
            "org_id": str(cmd.org_id),
            "terminal_id": cmd.terminal_id,
            "sync_type": cmd.sync_type,
            "synced_positions": synced_positions,
            "closed_positions": closed_positions,
            "synced_orders": synced_orders,
            "account_synced": account_synced,
        },
    )
    _log.info("terminal_synced", terminal_id=cmd.terminal_id, sync_type=cmd.sync_type)
    return SyncTerminalResult(
        terminal_id=cmd.terminal_id,
        synced_positions=synced_positions,
        closed_positions=closed_positions,
        account_synced=account_synced,
        synced_orders=synced_orders,
        last_synced_at=now.isoformat(),
    )
