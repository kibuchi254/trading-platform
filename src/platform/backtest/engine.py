"""Backtesting engine — runs a strategy against historical data using a paper broker.

The engine is intentionally simple: load candles, iterate bar-by-bar, feed each bar
to the strategy, route any returned signal through the risk engine and the paper
broker, then compute performance metrics at the end. The same code path runs in
backtest and in live mode (live mode uses the BridgeClient adapter instead of
PaperBrokerAdapter), eliminating backtest/live divergence.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform.core.logging import get_logger
from platform.core.telemetry import TASK_DURATION
from platform.db.models import Backtest as BacktestModel, Strategy, Trade
from platform.db.session import db_context
from platform.infrastructure.execution.paper_broker import PaperBrokerAdapter
from platform.risk.engine import get_risk_engine
from platform.strategies.sdk import Bar, StrategyContext, get_strategy_registry
from platform.backtest.metrics import (
    compute_avg_trade_duration, compute_equity_curve, compute_max_drawdown,
    compute_profit_factor, compute_sharpe_ratio, compute_sortino_ratio,
    compute_win_rate, compute_returns,
)

_log = get_logger(__name__)


class BacktestConfig(BaseModel):
    symbol: str
    timeframe: str
    start: datetime
    end: datetime
    initial_capital: float = 10_000.0
    strategy_name: str
    strategy_config: dict = Field(default_factory=dict)
    spread_points: int = 10
    commission_per_lot: float = 7.0
    org_id: UUID | None = None
    user_id: UUID | None = None


class BacktestResult(BaseModel):
    backtest_id: UUID
    status: str
    initial_capital: float
    final_equity: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe: float
    sortino: float
    win_rate: float
    profit_factor: float
    total_trades: int
    avg_duration_seconds: float
    best_trade: float
    worst_trade: float
    equity_curve: list[dict] = Field(default_factory=list)
    trades: list[dict] = Field(default_factory=list)
    error: str | None = None


class BacktestEngine:
    """Runs a single backtest, end-to-end.

    Usage:
        engine = BacktestEngine()
        result = await engine.run(backtest_id)
    """

    async def run(self, backtest_id: UUID) -> BacktestResult:
        """Load the backtest row, run, persist results, return."""
        start_ts = datetime.now(timezone.utc)
        with TASK_DURATION.labels(task="backtest").time():
            async with db_context() as db:
                bt = await db.get(BacktestModel, backtest_id)
                if bt is None:
                    return BacktestResult(
                        backtest_id=backtest_id, status="failed",
                        initial_capital=0, final_equity=0, total_return_pct=0,
                        max_drawdown_pct=0, sharpe=0, sortino=0, win_rate=0,
                        profit_factor=0, total_trades=0, avg_duration_seconds=0,
                        best_trade=0, worst_trade=0, error="Backtest not found",
                    )
                # Update status to running
                bt.status = "running"
                await db.commit()

                config = BacktestConfig(
                    symbol=bt.symbol,
                    timeframe=bt.timeframe,
                    start=bt.start,
                    end=bt.end,
                    initial_capital=float(bt.initial_capital),
                    strategy_name=bt.config.get("strategy_name", "ema_cross"),
                    strategy_config=bt.config.get("strategy_config", {}),
                    spread_points=bt.config.get("spread_points", 10),
                    commission_per_lot=bt.config.get("commission_per_lot", 7.0),
                    org_id=bt.org_id,
                    user_id=None,
                )

            try:
                result = await self._run_backtest(backtest_id, config)
            except Exception as e:
                _log.exception("backtest_failed", backtest_id=str(backtest_id))
                result = BacktestResult(
                    backtest_id=backtest_id, status="failed",
                    initial_capital=config.initial_capital, final_equity=0,
                    total_return_pct=0, max_drawdown_pct=0, sharpe=0, sortino=0,
                    win_rate=0, profit_factor=0, total_trades=0,
                    avg_duration_seconds=0, best_trade=0, worst_trade=0,
                    error=str(e),
                )

            # Persist results
            await self._persist_result(backtest_id, result)

            elapsed = (datetime.now(timezone.utc) - start_ts).total_seconds()
            _log.info(
                "backtest_completed",
                backtest_id=str(backtest_id), status=result.status,
                elapsed_seconds=elapsed, total_trades=result.total_trades,
                sharpe=result.sharpe,
            )
            return result

    async def _run_backtest(self, backtest_id: UUID, config: BacktestConfig) -> BacktestResult:
        # Load strategy
        registry = get_strategy_registry()
        try:
            strategy = registry.create(config.strategy_name, config.strategy_config)
        except KeyError as e:
            raise ValueError(f"Unknown strategy: {config.strategy_name}") from e

        # Load historical candles
        bars = await self._load_candles(config)
        if not bars:
            raise ValueError(
                f"No candles found for {config.symbol} {config.timeframe} "
                f"between {config.start} and {config.end}"
            )

        # Initialize paper broker
        broker = PaperBrokerAdapter()
        await broker.connect()
        broker._account = type(broker._account)(
            balance=config.initial_capital,
            equity=config.initial_capital,
            margin=0,
            free_margin=config.initial_capital,
            currency="USD", leverage=100,
        )

        # Initialize risk engine
        risk = get_risk_engine()

        # Strategy context
        ctx = StrategyContext(
            org_id=config.org_id or uuid.UUID(int=0),
            terminal_id="backtest",
            strategy_id=backtest_id,
            config={**strategy.default_config, **config.strategy_config},
        )
        await strategy.on_start(ctx)

        # Iterate bars
        trades: list[dict] = []
        equity_snapshots: list[tuple[datetime, float]] = []
        point = 10 ** -5  # default digits for FX
        spread = config.spread_points * point

        for bar in bars:
            # Update broker with current bar
            mid = bar.close
            await broker.update_ticks(config.symbol, mid - spread / 2, mid + spread / 2)

            # Build Bar object for strategy
            strategy_bar = Bar(
                symbol=config.symbol, timeframe=config.timeframe, ts=bar.ts,
                open=bar.open, high=bar.high, low=bar.low, close=bar.close,
                volume=bar.volume, is_closed=True,
            )

            # Run strategy
            try:
                signal = await asyncio.wait_for(
                    strategy.on_bar(strategy_bar, ctx), timeout=1.0
                )
            except asyncio.TimeoutError:
                _log.warning("strategy_timeout", bar_ts=bar.ts.isoformat())
                continue
            except Exception:
                _log.exception("strategy_error", bar_ts=bar.ts.isoformat())
                continue

            # Process signal
            if signal is not None and signal.strength > 0:
                try:
                    await risk.check_order(
                        org_id=ctx.org_id, terminal_id="backtest",
                        symbol=signal.symbol, side=signal.side,
                        volume=signal.suggested_volume or 0.01,
                    )
                except Exception:
                    continue  # risk rejected

                from platform.infrastructure.execution.adapter_base import OrderRequest
                req = OrderRequest(
                    client_order_id=f"bt-{uuid.uuid4().hex[:8]}",
                    symbol=signal.symbol,
                    side=signal.side,
                    order_type="market",
                    volume=signal.suggested_volume or 0.01,
                    stop_loss=signal.suggested_stop_loss,
                    take_profit=signal.suggested_take_profit,
                )
                try:
                    await broker.place_order(req)
                except Exception:
                    _log.exception("backtest_place_order_failed")

            # Snapshot equity
            acct = await broker.sync_account()
            equity_snapshots.append((bar.ts, acct.equity))

        # Close all open positions at the last close
        positions = await broker.sync_positions()
        last_price = bars[-1].close
        for pos in positions:
            try:
                await broker.close_position(pos.broker_position_id)
            except Exception:
                _log.exception("backtest_close_failed", position_id=pos.broker_position_id)

        # Collect trades
        for pos_id, pos_snap in broker._positions.items():
            if pos_snap.realized_pnl != 0 or True:  # capture all
                trades.append({
                    "symbol": pos_snap.symbol,
                    "side": pos_snap.side,
                    "volume": pos_snap.volume,
                    "entry_price": pos_snap.open_price,
                    "exit_price": pos_snap.current_price,
                    "pnl": getattr(pos_snap, "realized_pnl", 0.0),
                    "duration_seconds": 0,  # not tracked in paper broker for now
                    "opened_at": pos_snap.opened_at.isoformat(),
                    "closed_at": bar.ts.isoformat(),
                })

        await strategy.on_stop(ctx)
        await broker.disconnect()

        # Compute metrics
        final_equity = equity_snapshots[-1][1] if equity_snapshots else config.initial_capital
        curve = compute_equity_curve(trades, config.initial_capital)
        # Use equity_snapshots directly for drawdown
        max_dd = compute_max_drawdown(equity_snapshots)
        returns = compute_returns(equity_snapshots)
        sharpe = compute_sharpe_ratio(returns)
        sortino = compute_sortino_ratio(returns)
        win_rate = compute_win_rate(trades)
        profit_factor = compute_profit_factor(trades)
        avg_dur = compute_avg_trade_duration(trades)
        pnls = [float(t.get("pnl", 0)) for t in trades]
        best = max(pnls) if pnls else 0
        worst = min(pnls) if pnls else 0

        return BacktestResult(
            backtest_id=backtest_id, status="completed",
            initial_capital=config.initial_capital, final_equity=final_equity,
            total_return_pct=((final_equity - config.initial_capital) / config.initial_capital) * 100,
            max_drawdown_pct=max_dd * 100,
            sharpe=sharpe, sortino=sortino, win_rate=win_rate,
            profit_factor=profit_factor, total_trades=len(trades),
            avg_duration_seconds=avg_dur, best_trade=best, worst_trade=worst,
            equity_curve=[{"ts": ts.isoformat(), "equity": eq} for ts, eq in equity_snapshots],
            trades=trades,
        )

    async def _load_candles(self, config: BacktestConfig) -> list:
        """Load historical candles from DB."""
        from platform.db.models import Candle
        async with db_context() as db:
            stmt = (
                select(Candle)
                .where(
                    Candle.symbol == config.symbol,
                    Candle.timeframe == config.timeframe,
                    Candle.ts >= config.start,
                    Candle.ts <= config.end,
                )
                .order_by(Candle.ts.asc())
            )
            result = await db.execute(stmt)
            return list(result.scalars().all())

    async def _persist_result(self, backtest_id: UUID, result: BacktestResult) -> None:
        async with db_context() as db:
            bt = await db.get(BacktestModel, backtest_id)
            if bt is None:
                return
            bt.status = result.status
            bt.final_equity = result.final_equity
            bt.max_drawdown = result.max_drawdown_pct / 100
            bt.sharpe = result.sharpe
            bt.trades_count = result.total_trades
            bt.results = {
                "total_return_pct": result.total_return_pct,
                "sortino": result.sortino,
                "win_rate": result.win_rate,
                "profit_factor": result.profit_factor,
                "avg_duration_seconds": result.avg_duration_seconds,
                "best_trade": result.best_trade,
                "worst_trade": result.worst_trade,
                "equity_curve": result.equity_curve,
                "trades": result.trades,
                "error": result.error,
            }
            await db.commit()


__all__ = ["BacktestEngine", "BacktestConfig", "BacktestResult"]
