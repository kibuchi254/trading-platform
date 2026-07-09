"""Market Data REST router — historical candles, latest ticks, symbol metadata."""

from __future__ import annotations

from datetime import datetime
from platform.core.dependencies import CurrentUser, get_current_user
from platform.db.models import Candle, Symbol
from platform.db.session import get_db

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/market-data", tags=["market-data"])


class CandleOut(BaseModel):
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    model_config = {"from_attributes": True}


@router.get("/candles/{symbol}", response_model=list[CandleOut])
async def candles(
    symbol: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    timeframe: str = Query(default="M15"),
    limit: int = Query(default=500, le=5000),
) -> list[CandleOut]:
    stmt = (
        select(Candle)
        .where(Candle.symbol == symbol, Candle.timeframe == timeframe)
        .order_by(desc(Candle.ts))
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        CandleOut(
            ts=r.ts,
            open=float(r.open),
            high=float(r.high),
            low=float(r.low),
            close=float(r.close),
            volume=float(r.volume),
        )
        for r in reversed(rows)
    ]


@router.get("/symbols", response_model=list[dict[str, object]])
async def list_symbols(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, object]]:
    stmt = select(Symbol).limit(500)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "category": r.category,
            "digits": r.digits,
            "volume_min": float(r.volume_min),
            "volume_step": float(r.volume_step),
            "volume_max": float(r.volume_max),
        }
        for r in rows
    ]
