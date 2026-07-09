"""List closed trades for an org with optional filters.

Vertical slice:

  API → query → DB: select Trade rows by org_id (+ strategy / symbol / since filters)
        → return DTOs

Trades are append-only historical records produced when a Position closes
(see :mod:`platform.application.commands.close_position`). They are the
input to the analytics / performance queries.
"""

from __future__ import annotations

from datetime import datetime
from platform.db.models import Trade
from platform.db.session import db_context
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select

# ── Query + DTO ────────────────────────────────────────────────────────────


class ListTradesQuery(BaseModel):
    org_id: UUID
    strategy_id: UUID | None = None
    symbol: str | None = None
    since: datetime | None = None
    limit: int = 100


class TradeSummary(BaseModel):
    id: UUID
    position_id: UUID
    strategy_id: UUID | None
    symbol: str
    side: str
    volume: float
    entry_price: float
    exit_price: float
    pnl: float
    pips: float
    commission: float
    swap: float
    duration_seconds: int
    opened_at: datetime
    closed_at: datetime


class ListTradesResult(BaseModel):
    trades: list[TradeSummary]
    total: int


# ── Handler ─────────────────────────────────────────────────────────────────


async def handle_list_trades(query: ListTradesQuery) -> ListTradesResult:
    """Filter and paginate closed trades for the org."""
    limit = max(1, min(query.limit, 500))

    async with db_context() as db:
        stmt = select(Trade).where(Trade.org_id == query.org_id)
        if query.strategy_id is not None:
            stmt = stmt.where(Trade.strategy_id == query.strategy_id)
        if query.symbol is not None:
            stmt = stmt.where(Trade.symbol == query.symbol)
        if query.since is not None:
            stmt = stmt.where(Trade.closed_at >= query.since)
        stmt = stmt.order_by(Trade.closed_at.desc()).limit(limit)
        rows = (await db.execute(stmt)).scalars().all()

    trades = [
        TradeSummary(
            id=r.id,
            position_id=r.position_id,
            strategy_id=r.strategy_id,
            symbol=r.symbol,
            side=r.side,
            volume=float(r.volume or 0),
            entry_price=float(r.entry_price or 0),
            exit_price=float(r.exit_price or 0),
            pnl=float(r.pnl or 0),
            pips=float(r.pips or 0),
            commission=float(r.commission or 0),
            swap=float(r.swap or 0),
            duration_seconds=int(r.duration_seconds or 0),
            opened_at=r.opened_at,
            closed_at=r.closed_at,
        )
        for r in rows
    ]
    return ListTradesResult(trades=trades, total=len(trades))
