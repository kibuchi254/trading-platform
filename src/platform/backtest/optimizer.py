"""Optimization engine — grid search, random search, walk-forward analysis."""
from __future__ import annotations

import asyncio
import itertools
import random
import uuid
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select

from platform.backtest.engine import BacktestConfig, BacktestEngine, BacktestResult
from platform.backtest.metrics import compute_max_drawdown
from platform.core.logging import get_logger
from platform.db.models import Backtest, Strategy
from platform.db.session import db_context

_log = get_logger(__name__)


class OptimizationResult(BaseModel):
    backtest_id: UUID
    metric: str
    top_results: list[dict] = Field(default_factory=list)
    all_results_count: int = 0
    best_params: dict = Field(default_factory=dict)
    worst_params: dict = Field(default_factory=dict)
    avg_metric: float = 0.0


class WalkForwardResult(BaseModel):
    windows: int
    avg_test_metric: float
    std_test_metric: float
    robustness_score: float
    per_window_results: list[dict] = Field(default_factory=list)


class OptimizationEngine:
    """Grid/random search + walk-forward analysis."""

    def __init__(self, max_concurrent: int = 4) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def optimize(
        self,
        base_config: BacktestConfig,
        param_grid: dict[str, list],
        metric: str = "sharpe",
        mode: str = "grid",
        n_samples: int = 20,
        top_n: int = 10,
    ) -> OptimizationResult:
        """Run optimization. Returns ranked results."""
        combinations = self._generate_combinations(param_grid, mode, n_samples)
        _log.info(
            "optimization_starting",
            mode=mode, combinations=len(combinations), metric=metric,
        )

        # Run all backtests concurrently (bounded)
        tasks = [self._run_one(base_config, params) for params in combinations]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Build (params, result) list, filter failures
        scored: list[dict] = []
        for params, res in zip(combinations, results):
            if isinstance(res, Exception):
                _log.warning("optimization_run_failed", params=params, error=str(res))
                continue
            score = self._extract_metric(res, metric)
            scored.append({
                "params": params,
                "score": score,
                "total_trades": res.total_trades,
                "total_return_pct": res.total_return_pct,
                "max_drawdown_pct": res.max_drawdown_pct,
                "win_rate": res.win_rate,
                "profit_factor": res.profit_factor,
            })

        if not scored:
            return OptimizationResult(
                backtest_id=uuid.uuid4(), metric=metric,
                all_results_count=0,
            )

        # Sort descending (higher is better for most metrics; for max_drawdown lower is better)
        reverse = metric != "max_drawdown_pct"
        scored.sort(key=lambda x: x["score"], reverse=reverse)

        avg = sum(s["score"] for s in scored) / len(scored)

        return OptimizationResult(
            backtest_id=uuid.uuid4(), metric=metric,
            top_results=scored[:top_n],
            all_results_count=len(scored),
            best_params=scored[0]["params"] if scored else {},
            worst_params=scored[-1]["params"] if scored else {},
            avg_metric=avg,
        )

    async def walk_forward(
        self,
        base_config: BacktestConfig,
        param_grid: dict[str, list],
        train_days: int = 90,
        test_days: int = 30,
        windows: int = 4,
        metric: str = "sharpe",
    ) -> WalkForwardResult:
        """Walk-forward optimization: train on window N, test on window N+1."""
        from datetime import timedelta

        per_window: list[dict] = []
        test_scores: list[float] = []
        start = base_config.start

        for w in range(windows):
            train_start = start + timedelta(days=w * test_days)
            train_end = train_start + timedelta(days=train_days)
            test_start = train_end
            test_end = test_start + timedelta(days=test_days)

            if test_end > base_config.end:
                break

            # Optimize on train
            train_config = base_config.model_copy(update={"start": train_start, "end": train_end})
            train_result = await self.optimize(
                train_config, param_grid, metric=metric, mode="grid", top_n=1,
            )

            if not train_result.best_params:
                continue

            # Test on out-of-sample
            test_config = base_config.model_copy(
                update={
                    "start": test_start, "end": test_end,
                    "strategy_config": {**base_config.strategy_config, **train_result.best_params},
                }
            )
            async with self._semaphore:
                test_bt_id = await self._create_backtest_row(test_config)
                engine = BacktestEngine()
                test_res = await engine.run(test_bt_id)
                test_score = self._extract_metric(test_res, metric)

            test_scores.append(test_score)
            per_window.append({
                "window": w + 1,
                "train_start": train_start.isoformat(),
                "train_end": train_end.isoformat(),
                "test_start": test_start.isoformat(),
                "test_end": test_end.isoformat(),
                "best_params": train_result.best_params,
                "train_score": train_result.best_params and train_result.top_results[0]["score"],
                "test_score": test_score,
            })

        avg_test = sum(test_scores) / len(test_scores) if test_scores else 0
        var = sum((s - avg_test) ** 2 for s in test_scores) / len(test_scores) if test_scores else 0
        std_test = var ** 0.5
        # Robustness = avg / (std + epsilon) — higher is better
        robustness = avg_test / (std_test + 1e-9) if std_test > 0 else float("inf") if avg_test > 0 else 0

        return WalkForwardResult(
            windows=len(per_window),
            avg_test_metric=avg_test,
            std_test_metric=std_test,
            robustness_score=robustness,
            per_window_results=per_window,
        )

    # ── Internals ──────────────────────────────────────────────────────────

    @staticmethod
    def _generate_combinations(
        param_grid: dict[str, list], mode: str, n_samples: int
    ) -> list[dict[str, Any]]:
        keys = list(param_grid.keys())
        if mode == "grid":
            return [dict(zip(keys, vals)) for vals in itertools.product(*param_grid.values())]
        elif mode == "random":
            combos: list[dict] = []
            for _ in range(n_samples):
                combos.append({k: random.choice(v) for k, v in param_grid.items()})
            return combos
        else:
            raise ValueError(f"Unknown mode: {mode}")

    async def _run_one(self, base_config: BacktestConfig, params: dict) -> BacktestResult:
        async with self._semaphore:
            config = base_config.model_copy(
                update={"strategy_config": {**base_config.strategy_config, **params}}
            )
            bt_id = await self._create_backtest_row(config)
            engine = BacktestEngine()
            return await engine.run(bt_id)

    async def _create_backtest_row(self, config: BacktestConfig) -> UUID:
        async with db_context() as db:
            # Resolve strategy_id from name
            stmt = select(Strategy).where(
                Strategy.org_id == config.org_id,
                Strategy.kind == config.strategy_name,
            )
            strat = (await db.execute(stmt)).scalar_one_or_none()

            bt = Backtest(
                org_id=config.org_id or uuid.UUID(int=0),
                strategy_id=strat.id if strat else uuid.UUID(int=0),
                symbol=config.symbol,
                timeframe=config.timeframe,
                start=config.start,
                end=config.end,
                initial_capital=config.initial_capital,
                status="pending",
                config={
                    "strategy_name": config.strategy_name,
                    "strategy_config": config.strategy_config,
                    "spread_points": config.spread_points,
                    "commission_per_lot": config.commission_per_lot,
                },
            )
            db.add(bt)
            await db.commit()
            await db.refresh(bt)
            return bt.id

    @staticmethod
    def _extract_metric(result: BacktestResult, metric: str) -> float:
        mapping = {
            "sharpe": result.sharpe,
            "sortino": result.sortino,
            "total_return_pct": result.total_return_pct,
            "win_rate": result.win_rate,
            "profit_factor": result.profit_factor,
            "max_drawdown_pct": -abs(result.max_drawdown_pct),  # negate so higher=better
            "final_equity": result.final_equity,
        }
        return mapping.get(metric, 0.0)


__all__ = ["OptimizationEngine", "OptimizationResult", "WalkForwardResult"]
