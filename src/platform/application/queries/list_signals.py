"""List recent trading signals for an org with optional filters.

Vertical slice:

  API → query → DB: select Signal rows by org_id (+ strategy / symbol filters)
        → return DTOs

Signals are emitted by strategies / AI modules (see :class:`Signal` ORM).
The query returns the most recent N signals for the org, scoped by the
optional strategy_id / symbol filters.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select

from platform.db.models import Signal as SignalModel
from platform.db.session import db_context


# ── Query + DTO ────────────────────────────────────────────────────────────


class ListSignalsQuery(BaseModel):
    org_id: UUID
    strategy_id: UUID | None = None
    symbol: str | None = None
    limit: int = 50


class SignalSummary(BaseModel):
    id: UUID
    strategy_id: UUID
    terminal_id: UUID
    symbol: str
    side: str
    strength: float
    timeframe: str
    price: float
    source: str
    meta: dict
    created_at: datetime


class ListSignalsResult(BaseModel):
    signals: list[SignalSummary]
    total: int


# ── Handler ─────────────────────────────────────────────────────────────────


async def handle_list_signals(query: ListSignalsQuery) -> ListSignalsResult:
    """Filter and paginate the most recent signals for the org."""
    limit = max(1, min(query.limit, 500))

    async with db_context() as db:
        stmt = select(SignalModel).where(SignalModel.org_id == query.org_id)
        if query.strategy_id is not None:
            stmt = stmt.where(SignalModel.strategy_id == query.strategy_id)
        if query.symbol is not None:
            stmt = stmt.where(SignalModel.symbol == query.symbol)
        stmt = stmt.order_by(SignalModel.created_at.desc()).limit(limit)
        rows = (await db.execute(stmt)).scalars().all()

    signals = [
        SignalSummary(
            id=r.id,
            strategy_id=r.strategy_id,
            terminal_id=r.terminal_id,
            symbol=r.symbol,
            side=r.side,
            strength=float(r.strength or 0),
            timeframe=r.timeframe,
            price=float(r.price or 0),
            source=r.source,
            meta=dict(r.meta or {}),
            created_at=r.created_at,
        )
        for r in rows
    ]
    return ListSignalsResult(signals=signals, total=len(signals))
