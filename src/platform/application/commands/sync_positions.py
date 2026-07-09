"""Force terminal position sync — pull all open positions from MT5 and reconcile."""

from __future__ import annotations

from datetime import UTC, datetime
from platform.core.exceptions import NotFoundError
from platform.core.logging import get_logger
from platform.db.models import Position, Terminal
from platform.db.session import db_context
from platform.infrastructure.mt5_bridge.client import get_bridge_client
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select

_log = get_logger(__name__)


class SyncPositionsCommand(BaseModel):
    org_id: UUID
    user_id: UUID
    terminal_id: str  # external


class SyncPositionsResult(BaseModel):
    terminal_id: str
    synced_count: int
    closed_count: int


async def handle_sync_positions(cmd: SyncPositionsCommand) -> SyncPositionsResult:
    bridge = get_bridge_client()
    reply = await bridge.sync_positions(terminal_id=cmd.terminal_id, timeout=30.0)
    remote_positions = reply.payload.get("positions", [])

    async with db_context() as db:
        # Get terminal internal id
        stmt = select(Terminal).where(
            Terminal.terminal_id == cmd.terminal_id, Terminal.org_id == cmd.org_id
        )
        terminal = (await db.execute(stmt)).scalar_one_or_none()
        if terminal is None:
            raise NotFoundError(f"Terminal {cmd.terminal_id} not found")

        # Get currently-open DB positions
        db_open = (
            (
                await db.execute(
                    select(Position).where(
                        Position.terminal_id == terminal.id, Position.status == "open"
                    )
                )
            )
            .scalars()
            .all()
        )
        db_by_broker_id = {p.broker_position_id: p for p in db_open if p.broker_position_id}

        remote_broker_ids = set()
        for rp in remote_positions:
            broker_id = str(rp.get("broker_position_id"))
            remote_broker_ids.add(broker_id)
            existing = db_by_broker_id.get(broker_id)
            if existing is None:
                # New position — insert
                p = Position(
                    org_id=cmd.org_id,
                    terminal_id=terminal.id,
                    broker_position_id=broker_id,
                    symbol=rp["symbol"],
                    side=rp["side"],
                    volume=float(rp["volume"]),
                    open_price=float(rp["open_price"]),
                    current_price=float(rp["current_price"]),
                    stop_loss=float(rp.get("stop_loss")) if rp.get("stop_loss") else None,
                    take_profit=float(rp.get("take_profit")) if rp.get("take_profit") else None,
                    swap=float(rp.get("swap", 0)),
                    unrealized_pnl=float(rp.get("unrealized_pnl", 0)),
                    opened_at=datetime.fromisoformat(rp["opened_at"].replace("Z", "+00:00"))
                    if isinstance(rp["opened_at"], str)
                    else datetime.now(UTC),
                )
                db.add(p)
            else:
                # Update existing
                existing.current_price = float(rp["current_price"])
                existing.volume = float(rp["volume"])
                if rp.get("stop_loss"):
                    existing.stop_loss = float(rp["stop_loss"])
                if rp.get("take_profit"):
                    existing.take_profit = float(rp["take_profit"])
                existing.swap = float(rp.get("swap", existing.swap))
                existing.unrealized_pnl = float(rp.get("unrealized_pnl", existing.unrealized_pnl))

        # Mark DB positions not in remote as closed (broker no longer reports them)
        closed_count = 0
        for broker_id, p in db_by_broker_id.items():
            if broker_id not in remote_broker_ids:
                p.status = "closed"
                p.closed_at = datetime.now(UTC)
                closed_count += 1

        await db.commit()
        synced = len(remote_positions)
        _log.info(
            "positions_synced", terminal_id=cmd.terminal_id, synced=synced, closed=closed_count
        )

    return SyncPositionsResult(
        terminal_id=cmd.terminal_id,
        synced_count=synced,
        closed_count=closed_count,
    )
