"""Modify SL/TP on an open position.

Vertical slice:

  API → command → load Position → resolve external terminal_id
        → bridge MODIFY_POSITION → persist updated SL/TP
        → publish POSITION_UPDATES event

The :class:`BridgeClient` does not expose a high-level `modify_position`,
so the handler builds the raw ``MODIFY_POSITION`` command via the protocol
helpers and enqueues it through the command queue — same pattern used by
:class:`BridgeClientAdapter.modify_position`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select

from platform.core.exceptions import NotFoundError, ValidationError
from platform.core.logging import get_logger
from platform.db.models import Position, Terminal
from platform.db.session import db_context
from platform.events.bus import get_event_bus
from platform.events.topics import Topic
from platform.infrastructure.mt5_bridge.command_queue import get_command_queue
from platform.infrastructure.mt5_bridge.protocol import CommandType, command
from platform.infrastructure.mt5_bridge.registry import get_registry

_log = get_logger(__name__)


# ── Command + DTO ──────────────────────────────────────────────────────────


class ModifyPositionCommand(BaseModel):
    org_id: UUID
    user_id: UUID
    position_id: UUID
    stop_loss: float | None = None
    take_profit: float | None = None


class ModifyPositionResult(BaseModel):
    position_id: UUID
    status: str = "modified"
    stop_loss: float | None = None
    take_profit: float | None = None


# ── Handler ─────────────────────────────────────────────────────────────────


async def handle_modify_position(cmd: ModifyPositionCommand) -> ModifyPositionResult:
    """Forward a MODIFY_POSITION command to the terminal and persist the new SL/TP."""
    if cmd.stop_loss is None and cmd.take_profit is None:
        raise ValidationError("At least one of stop_loss / take_profit must be provided")

    async with db_context() as db:
        pos = await db.get(Position, cmd.position_id)
        if pos is None or pos.org_id != cmd.org_id:
            raise NotFoundError(f"Position {cmd.position_id} not found")
        if pos.status != "open":
            raise ValidationError(f"Cannot modify position in status {pos.status}")
        if not pos.broker_position_id:
            raise ValidationError("Position has no broker_position_id")

        terminal = (
            await db.execute(select(Terminal).where(Terminal.id == pos.terminal_id))
        ).scalar_one_or_none()
        if terminal is None:
            raise NotFoundError("Terminal for position not found")

        registry = get_registry()
        rec = await registry.require(terminal.terminal_id)
        cmd_msg = command(
            CommandType.MODIFY_POSITION,
            terminal_id=terminal.terminal_id,
            payload={
                "broker_position_id": pos.broker_position_id,
                "stop_loss": cmd.stop_loss,
                "take_profit": cmd.take_profit,
            },
        )
        await rec.session.send(cmd_msg)
        await get_command_queue().enqueue(cmd_msg, timeout=10.0)

        if cmd.stop_loss is not None:
            pos.stop_loss = cmd.stop_loss
        if cmd.take_profit is not None:
            pos.take_profit = cmd.take_profit
        pos.updated_at = datetime.now(timezone.utc)
        await db.commit()

        result = ModifyPositionResult(
            position_id=pos.id,
            stop_loss=float(pos.stop_loss) if pos.stop_loss is not None else None,
            take_profit=float(pos.take_profit) if pos.take_profit is not None else None,
        )

    await get_event_bus().publish(
        Topic.POSITION_UPDATES,
        {
            "type": "position_modified",
            "org_id": str(cmd.org_id),
            "position_id": str(result.position_id),
            "stop_loss": result.stop_loss,
            "take_profit": result.take_profit,
            "actor_id": str(cmd.user_id),
        },
    )
    _log.info("position_modified", position_id=str(result.position_id))
    return result
