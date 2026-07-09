"""TradeRepository — read-only-ish persistence for closed Trade rows.

A Trade is the immutable historical record produced when a Position closes.
The repository therefore exposes `add` (insert) but no `save` (no updates).
The headline method is `performance_summary` which folds the closed-trade
stream into the KPIs shown on the analytics dashboard.
"""

from __future__ import annotations

from datetime import datetime
from platform.db.models import Trade as TradeModel
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


class TradeRepository:
    """Async repository for the Trade ORM model."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Conversions ─────────────────────────────────────────────────────────
    # No domain aggregate exists for Trade — it is a pure historical record.
    # The to_domain / from_domain pass-throughs keep the repository shape
    # consistent and let a future aggregate be slotted in transparently.

    @staticmethod
    def to_domain(m: TradeModel) -> TradeModel:
        return m

    @staticmethod
    def from_domain(e: TradeModel) -> TradeModel:
        return e

    # ── Reads ───────────────────────────────────────────────────────────────

    async def get(self, id: UUID) -> TradeModel | None:
        return await self.db.get(TradeModel, id)

    async def list_by_org(
        self,
        org_id: UUID,
        *,
        symbol: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[TradeModel]:
        stmt = select(TradeModel).where(TradeModel.org_id == org_id)
        if symbol:
            stmt = stmt.where(TradeModel.symbol == symbol)
        stmt = stmt.order_by(TradeModel.closed_at.desc()).limit(limit).offset(offset)
        return list((await self.db.execute(stmt)).scalars().all())

    async def list_by_strategy(
        self,
        strategy_id: UUID,
        *,
        limit: int = 200,
    ) -> list[TradeModel]:
        stmt = (
            select(TradeModel)
            .where(TradeModel.strategy_id == strategy_id)
            .order_by(TradeModel.closed_at.desc())
            .limit(limit)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def list_by_symbol(
        self,
        org_id: UUID,
        symbol: str,
        *,
        limit: int = 200,
    ) -> list[TradeModel]:
        stmt = (
            select(TradeModel)
            .where(TradeModel.org_id == org_id, TradeModel.symbol == symbol)
            .order_by(TradeModel.closed_at.desc())
            .limit(limit)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    # ── Writes ──────────────────────────────────────────────────────────────

    async def add(self, entity: TradeModel) -> TradeModel:
        self.db.add(entity)
        await self.db.flush()
        return entity

    # ── Aggregations ────────────────────────────────────────────────────────

    async def performance_summary(
        self,
        org_id: UUID,
        since: datetime,
    ) -> dict[str, float | int | None]:
        """Fold closed trades for `org_id` since `since` into KPI metrics.

        Returns: total_trades, win_rate, total_pnl, avg_pnl, best, worst,
        avg_duration (seconds). Wins are trades with pnl > 0.
        """
        base = select(TradeModel).where(
            TradeModel.org_id == org_id,
            TradeModel.closed_at >= since,
        )

        count_stmt = select(func.count()).select_from(base.subquery())
        total_trades: int = (await self.db.execute(count_stmt)).scalar_one()

        if total_trades == 0:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "avg_pnl": 0.0,
                "best": None,
                "worst": None,
                "avg_duration": 0.0,
            }

        agg_stmt = select(
            func.sum(TradeModel.pnl).label("total_pnl"),
            func.avg(TradeModel.pnl).label("avg_pnl"),
            func.max(TradeModel.pnl).label("best"),
            func.min(TradeModel.pnl).label("worst"),
            func.avg(TradeModel.duration_seconds).label("avg_duration"),
            func.sum(func.case((TradeModel.pnl > 0, 1), else_=0)).label("wins"),
        ).where(TradeModel.org_id == org_id, TradeModel.closed_at >= since)
        row = (await self.db.execute(agg_stmt)).one()
        wins: int = int(row.wins or 0)
        return {
            "total_trades": total_trades,
            "win_rate": wins / total_trades,
            "total_pnl": float(row.total_pnl or 0),
            "avg_pnl": float(row.avg_pnl or 0),
            "best": float(row.best) if row.best is not None else None,
            "worst": float(row.worst) if row.worst is not None else None,
            "avg_duration": float(row.avg_duration or 0),
        }
