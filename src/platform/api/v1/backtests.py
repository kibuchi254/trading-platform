"""Backtests REST router — list / create / detail.

Wraps the `run_backtest` command and the `BacktestRepository`. The simulation
runs out-of-process on a Celery worker; the create endpoint returns immediately
and the caller polls `GET /backtests/{id}` for results.
"""

from __future__ import annotations

from datetime import datetime
from platform.application.commands.run_backtest import RunBacktestCommand, handle_run_backtest
from platform.core.dependencies import CurrentUser, get_current_user
from platform.core.exceptions import NotFoundError
from platform.db.models import Backtest
from platform.db.session import get_db
from platform.infrastructure.repositories.backtest_repository import BacktestRepository
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/backtests", tags=["backtests"])


class BacktestCreate(BaseModel):
    strategy_id: UUID
    symbol: str
    timeframe: str
    start: datetime
    end: datetime
    initial_capital: float = Field(default=10_000.0, gt=0)
    config: dict[str, Any] = {}


class BacktestOut(BaseModel):
    id: UUID
    strategy_id: UUID
    symbol: str
    timeframe: str
    start: datetime
    end: datetime
    initial_capital: float
    final_equity: float | None
    max_drawdown: float | None
    sharpe: float | None
    trades_count: int
    status: str
    config: dict
    results: dict
    created_at: datetime

    model_config = {"from_attributes": True}


def _to_out(bt: Backtest) -> BacktestOut:
    return BacktestOut(
        id=bt.id,
        strategy_id=bt.strategy_id,
        symbol=bt.symbol,
        timeframe=bt.timeframe,
        start=bt.start,
        end=bt.end,
        initial_capital=float(bt.initial_capital),
        final_equity=float(bt.final_equity) if bt.final_equity is not None else None,
        max_drawdown=float(bt.max_drawdown) if bt.max_drawdown is not None else None,
        sharpe=float(bt.sharpe) if bt.sharpe is not None else None,
        trades_count=bt.trades_count,
        status=bt.status,
        config=dict(bt.config or {}),
        results=dict(bt.results or {}),
        created_at=bt.created_at,
    )


@router.get("", response_model=list[BacktestOut])
async def list_backtests(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, le=200),
) -> list[BacktestOut]:
    repo = BacktestRepository(db)
    rows = await repo.list_by_org(user.org_id, limit=limit)
    return [_to_out(r) for r in rows]


@router.post("", status_code=201)
async def create_backtest(
    req: BacktestCreate,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    result = await handle_run_backtest(
        RunBacktestCommand(
            org_id=user.org_id,
            user_id=user.user_id,
            strategy_id=req.strategy_id,
            symbol=req.symbol,
            timeframe=req.timeframe,
            start=req.start,
            end=req.end,
            initial_capital=req.initial_capital,
            config=req.config,
        )
    )
    return result.model_dump(mode="json")


@router.get("/{backtest_id}", response_model=BacktestOut)
async def get_backtest(
    backtest_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BacktestOut:
    repo = BacktestRepository(db)
    bt = await repo.get(backtest_id)
    if bt is None or bt.org_id != user.org_id:
        raise NotFoundError(f"Backtest {backtest_id} not found")
    return _to_out(bt)
