"""Analytics REST router — trade history, performance, P&L summary."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from platform.core.dependencies import CurrentUser, get_current_user
from platform.db.models import Order, Position, Trade
from platform.db.session import get_db

router = APIRouter(prefix="/analytics", tags=["analytics"])


class PerformanceSummary(BaseModel):
    total_trades: int
    win_rate: float
    total_pnl: float
    avg_pnl: float
    best_trade: float
    worst_trade: float
    avg_duration_seconds: float


@router.get("/performance", response_model=PerformanceSummary)
async def performance(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    days: int = Query(default=30, le=365),
) -> PerformanceSummary:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = (
        select(Trade)
        .where(Trade.org_id == user.org_id, Trade.closed_at >= cutoff)
        .order_by(Trade.closed_at.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        return PerformanceSummary(
            total_trades=0, win_rate=0, total_pnl=0, avg_pnl=0,
            best_trade=0, worst_trade=0, avg_duration_seconds=0,
        )
    wins = sum(1 for t in rows if float(t.pnl) > 0)
    pnls = [float(t.pnl) for t in rows]
    return PerformanceSummary(
        total_trades=len(rows),
        win_rate=wins / len(rows),
        total_pnl=sum(pnls),
        avg_pnl=sum(pnls) / len(rows),
        best_trade=max(pnls),
        worst_trade=min(pnls),
        avg_duration_seconds=sum(t.duration_seconds for t in rows) / len(rows),
    )


@router.get("/positions/open")
async def open_positions(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, object]]:
    stmt = select(Position).where(
        Position.org_id == user.org_id, Position.status == "open"
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(r.id), "symbol": r.symbol, "side": r.side,
            "volume": float(r.volume), "open_price": float(r.open_price),
            "current_price": float(r.current_price),
            "unrealized_pnl": float(r.unrealized_pnl),
            "opened_at": r.opened_at.isoformat(),
        }
        for r in rows
    ]
