"""SignalRepository — persistence for the Signal aggregate.

Signals are append-mostly: they are emitted by strategies / AI modules, then
their status flips through PENDING → EVALUATED → EXECUTED/REJECTED/EXPIRED.
This repository therefore exposes `add` but no `save` (mutations go through
explicit status-update paths in the application layer).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from platform.db.models import Signal as SignalModel
from platform.domain.shared import Price, Symbol, Timeframe
from platform.domain.strategy import (
    Signal,
    SignalSide,
    SignalSource,
    SignalStrength,
)
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class SignalRepository:
    """Async repository for the Signal aggregate."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Conversions ─────────────────────────────────────────────────────────

    @staticmethod
    def to_domain(m: SignalModel) -> Signal:
        sig = Signal(
            id=m.id,
            org_id=m.org_id,
            strategy_id=m.strategy_id,
            terminal_id=m.terminal_id,
            symbol=Symbol(name=m.symbol),
            side=SignalSide(m.side),
            strength=SignalStrength(value=float(m.strength)),
            timeframe=Timeframe(code=m.timeframe),
            price=Price(value=float(m.price)),
            meta=m.meta or {},
            source=SignalSource(m.source),
            created_at=m.created_at,
        )
        # Side-channel ORM-only field for round-trip.
        sig._orm_status = m.status  # type: ignore[attr-defined]
        return sig

    @staticmethod
    def from_domain(e: Signal) -> SignalModel:
        return SignalModel(
            id=e.id,
            org_id=e.org_id,
            strategy_id=e.strategy_id,
            terminal_id=e.terminal_id,
            symbol=e.symbol.name,
            side=e.side.value,
            strength=e.strength.value,
            timeframe=e.timeframe.code,
            price=e.price.value,
            meta=e.meta,
            source=e.source.value,
        )

    # ── Reads ───────────────────────────────────────────────────────────────

    async def get(self, id: UUID) -> Signal | None:
        m = await self.db.get(SignalModel, id)
        return self.to_domain(m) if m else None

    async def list_by_strategy(
        self,
        strategy_id: UUID,
        *,
        limit: int = 100,
    ) -> list[Signal]:
        stmt = (
            select(SignalModel)
            .where(SignalModel.strategy_id == strategy_id)
            .order_by(SignalModel.created_at.desc())
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [self.to_domain(r) for r in rows]

    async def list_recent_by_org(
        self,
        org_id: UUID,
        *,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[Signal]:
        cutoff = since or (datetime.now(UTC) - timedelta(hours=24))
        stmt = (
            select(SignalModel)
            .where(SignalModel.org_id == org_id, SignalModel.created_at >= cutoff)
            .order_by(SignalModel.created_at.desc())
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [self.to_domain(r) for r in rows]

    async def list_by_symbol(
        self,
        org_id: UUID,
        symbol: str,
        *,
        limit: int = 100,
    ) -> list[Signal]:
        stmt = (
            select(SignalModel)
            .where(SignalModel.org_id == org_id, SignalModel.symbol == symbol)
            .order_by(SignalModel.created_at.desc())
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [self.to_domain(r) for r in rows]

    # ── Writes ──────────────────────────────────────────────────────────────

    async def add(self, entity: Signal) -> Signal:
        self.db.add(self.from_domain(entity))
        await self.db.flush()
        return entity
