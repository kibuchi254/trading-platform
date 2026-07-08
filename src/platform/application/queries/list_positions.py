"""List positions for an org with optional filters.

Vertical slice:

  API → query → DB: select Position rows by org_id (status + terminal_id filters)
        → return DTOs
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select

from platform.db.models import Position
from platform.db.session import db_context


# ── Query + DTO ────────────────────────────────────────────────────────────


class ListPositionsQuery(BaseModel):
    org_id: UUID
    status: str = "open"  # open | closed | all
    terminal_id: UUID | None = None  # internal terminal id
    limit: int = 200


class PositionSummary(BaseModel):
    id: UUID
    terminal_id: UUID
    broker_position_id: str | None
    symbol: str
    side: str
    volume: float
    open_price: float
    current_price: float
    stop_loss: float | None
    take_profit: float | None
    swap: float
    unrealized_pnl: float
    realized_pnl: float
    status: str
    opened_at: datetime
    closed_at: datetime | None


class ListPositionsResult(BaseModel):
    positions: list[PositionSummary]
    total: int


# ── Handler ─────────────────────────────────────────────────────────────────


async def handle_list_positions(query: ListPositionsQuery) -> ListPositionsResult:
    """Filter and paginate positions for the org."""
    limit = max(1, min(query.limit, 1000))

    async with db_context() as db:
        stmt = select(Position).where(Position.org_id == query.org_id)
        if query.status != "all":
            stmt = stmt.where(Position.status == query.status)
        if query.terminal_id is not None:
            stmt = stmt.where(Position.terminal_id == query.terminal_id)
        stmt = stmt.order_by(Position.opened_at.desc()).limit(limit)
        rows = (await db.execute(stmt)).scalars().all()

    positions = [
        PositionSummary(
            id=r.id,
            terminal_id=r.terminal_id,
            broker_position_id=r.broker_position_id,
            symbol=r.symbol,
            side=r.side,
            volume=float(r.volume or 0),
            open_price=float(r.open_price or 0),
            current_price=float(r.current_price or 0),
            stop_loss=float(r.stop_loss) if r.stop_loss is not None else None,
            take_profit=float(r.take_profit) if r.take_profit is not None else None,
            swap=float(r.swap or 0),
            unrealized_pnl=float(r.unrealized_pnl or 0),
            realized_pnl=float(r.realized_pnl or 0),
            status=r.status,
            opened_at=r.opened_at,
            closed_at=r.closed_at,
        )
        for r in rows
    ]
    return ListPositionsResult(positions=positions, total=len(positions))
