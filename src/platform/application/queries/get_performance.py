"""Aggregate performance metrics for an org (optionally per-strategy).

Vertical slice:

  API → query → DB: aggregate Trade rows over the trailing ``days`` window
        → compute KPIs (win rate, profit factor, max drawdown, ...)
        → return PerformanceSummary DTO

The headline metrics (total_trades, win_rate, total_pnl, avg_pnl, best,
worst, avg_duration) come from a single SQL fold. Profit factor is
``gross_profit / gross_loss`` (with ``None`` for no losers). Max drawdown
is computed in Python from the running PnL stream — a SQL window would be
faster but is awkward to express portably across PG / SQLite.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, select

from platform.db.models import Trade
from platform.db.session import db_context


# ── Query + DTO ────────────────────────────────────────────────────────────


class GetPerformanceQuery(BaseModel):
    org_id: UUID
    days: int = 30
    strategy_id: UUID | None = None


class PerformanceSummary(BaseModel):
    org_id: UUID
    strategy_id: UUID | None
    days: int
    total_trades: int
    win_rate: float
    total_pnl: float
    avg_pnl: float
    best_trade: float | None
    worst_trade: float | None
    avg_duration_seconds: float
    profit_factor: float | None
    max_drawdown: float


class GetPerformanceResult(BaseModel):
    summary: PerformanceSummary
    computed_at: str


# ── Handler ─────────────────────────────────────────────────────────────────


async def handle_get_performance(query: GetPerformanceQuery) -> GetPerformanceResult:
    """Fold the trailing-N-days trade stream into a KPI summary."""
    days = max(1, min(query.days, 365))
    since = datetime.now(timezone.utc) - timedelta(days=days)

    async with db_context() as db:
        base = select(Trade).where(Trade.org_id == query.org_id, Trade.closed_at >= since)
        if query.strategy_id is not None:
            base = base.where(Trade.strategy_id == query.strategy_id)

        # Aggregate metrics in one SQL round-trip.
        agg = select(
            func.count().label("total_trades"),
            func.sum(Trade.pnl).label("total_pnl"),
            func.avg(Trade.pnl).label("avg_pnl"),
            func.max(Trade.pnl).label("best"),
            func.min(Trade.pnl).label("worst"),
            func.avg(Trade.duration_seconds).label("avg_duration"),
            func.sum(func.case((Trade.pnl > 0, Trade.pnl), else_=0)).label("gross_profit"),
            func.sum(func.case((Trade.pnl < 0, Trade.pnl), else_=0)).label("gross_loss"),
            func.sum(func.case((Trade.pnl > 0, 1), else_=0)).label("wins"),
        ).where(Trade.org_id == query.org_id, Trade.closed_at >= since)
        if query.strategy_id is not None:
            agg = agg.where(Trade.strategy_id == query.strategy_id)
        row = (await db.execute(agg)).one()

        # Pull the ordered pnl stream for max-drawdown computation.
        pnl_stmt = (
            select(Trade.pnl)
            .where(Trade.org_id == query.org_id, Trade.closed_at >= since)
            .order_by(Trade.closed_at.asc())
        )
        if query.strategy_id is not None:
            pnl_stmt = pnl_stmt.where(Trade.strategy_id == query.strategy_id)
        pnl_stream = [float(p or 0) for p in (await db.execute(pnl_stmt)).scalars().all()]

    total_trades = int(row.total_trades or 0)
    wins = int(row.wins or 0)
    win_rate = (wins / total_trades) if total_trades else 0.0
    gross_profit = float(row.gross_profit or 0)
    gross_loss_abs = abs(float(row.gross_loss or 0))
    profit_factor = (
        (gross_profit / gross_loss_abs) if gross_loss_abs > 0 else None
    )
    max_drawdown = _max_drawdown(pnl_stream)

    summary = PerformanceSummary(
        org_id=query.org_id,
        strategy_id=query.strategy_id,
        days=days,
        total_trades=total_trades,
        win_rate=round(win_rate, 4),
        total_pnl=round(float(row.total_pnl or 0), 2),
        avg_pnl=round(float(row.avg_pnl or 0), 2),
        best_trade=round(float(row.best), 2) if row.best is not None else None,
        worst_trade=round(float(row.worst), 2) if row.worst is not None else None,
        avg_duration_seconds=round(float(row.avg_duration or 0), 2),
        profit_factor=round(profit_factor, 4) if profit_factor is not None else None,
        max_drawdown=round(max_drawdown, 2),
    )
    return GetPerformanceResult(
        summary=summary,
        computed_at=datetime.now(timezone.utc).isoformat(),
    )


def _max_drawdown(pnl_stream: list[float]) -> float:
    """Peak-to-trough drawdown on the cumulative PnL curve. Always <= 0."""
    if not pnl_stream:
        return 0.0
    peak = 0.0
    equity = 0.0
    worst = 0.0
    for pnl in pnl_stream:
        equity += pnl
        if equity > peak:
            peak = equity
        drawdown = equity - peak
        if drawdown < worst:
            worst = drawdown
    return worst
