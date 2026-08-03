"""Trades REST router — the closed-trade ledger (the "books").

Wraps the `list_trades` query. Org-scoped via the authenticated user.
"""

from __future__ import annotations

from datetime import datetime
from platform.application.queries.list_trades import ListTradesQuery, handle_list_trades
from platform.core.dependencies import CurrentUser, get_current_user
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

router = APIRouter(prefix="/trades", tags=["trades"])


class TradeOut(BaseModel):
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


@router.get("")
async def list_trades(
    user: CurrentUser = Depends(get_current_user),
    symbol: str | None = Query(default=None),
    strategy_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, le=500),
) -> dict:
    result = await handle_list_trades(
        ListTradesQuery(
            org_id=user.org_id,
            symbol=symbol,
            strategy_id=strategy_id,
            limit=limit,
        )
    )
    return result.model_dump(mode="json")
