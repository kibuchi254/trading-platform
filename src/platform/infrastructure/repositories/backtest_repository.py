"""BacktestRepository — persistence for the Backtest ORM model.

A Backtest row is created when a user kicks off a historical simulation and is
mutated twice during its lifecycle: when the worker picks it up (status →
running) and when it completes (status → completed + results JSONB blob). The
`update_status` method is the single mutation surface.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from platform.db.models import Backtest


class BacktestRepository:
    """Async repository for the Backtest ORM model."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Conversions ─────────────────────────────────────────────────────────
    # No dedicated domain aggregate for Backtest — to_domain / from_domain are
    # identity pass-throughs kept for shape-consistency.

    @staticmethod
    def to_domain(m: Backtest) -> Backtest:
        return m

    @staticmethod
    def from_domain(e: Backtest) -> Backtest:
        return e

    # ── Reads ───────────────────────────────────────────────────────────────

    async def get(self, id: UUID) -> Backtest | None:
        return await self.db.get(Backtest, id)

    async def list_by_org(
        self, org_id: UUID, *, limit: int = 50, offset: int = 0,
    ) -> list[Backtest]:
        stmt = (
            select(Backtest)
            .where(Backtest.org_id == org_id)
            .order_by(Backtest.created_at.desc())
            .limit(limit).offset(offset)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def list_by_strategy(
        self, strategy_id: UUID, *, limit: int = 50,
    ) -> list[Backtest]:
        stmt = (
            select(Backtest)
            .where(Backtest.strategy_id == strategy_id)
            .order_by(Backtest.created_at.desc())
            .limit(limit)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    # ── Writes ──────────────────────────────────────────────────────────────

    async def add(self, entity: Backtest) -> Backtest:
        self.db.add(entity)
        await self.db.flush()
        return entity

    async def save(self, entity: Backtest) -> Backtest:
        if entity not in self.db:
            self.db.add(entity)
        await self.db.flush()
        return entity

    async def update_status(
        self, id: UUID, status: str, results: dict | None = None,
    ) -> bool:
        """Transition the backtest status. When status is terminal
        ('completed' / 'failed') the `results` blob should be supplied."""
        values: dict = {
            "status": status,
            "updated_at": datetime.now(timezone.utc),
        }
        if results is not None:
            values["results"] = results
        stmt = update(Backtest).where(Backtest.id == id).values(**values)
        result = await self.db.execute(stmt)
        await self.db.flush()
        return (result.rowcount or 0) > 0
