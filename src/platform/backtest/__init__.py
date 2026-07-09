"""Backtesting subsystem."""

from platform.backtest.engine import BacktestConfig, BacktestEngine, BacktestResult
from platform.backtest.metrics import (
    compute_avg_trade_duration,
    compute_equity_curve,
    compute_expectancy,
    compute_max_drawdown,
    compute_profit_factor,
    compute_sharpe_ratio,
    compute_sortino_ratio,
    compute_win_rate,
)
from platform.backtest.optimizer import OptimizationEngine, OptimizationResult, WalkForwardResult
from platform.backtest.report import generate_json, generate_markdown

__all__ = [
    "BacktestConfig",
    "BacktestEngine",
    "BacktestResult",
    "OptimizationEngine",
    "OptimizationResult",
    "WalkForwardResult",
    "compute_avg_trade_duration",
    "compute_equity_curve",
    "compute_expectancy",
    "compute_max_drawdown",
    "compute_profit_factor",
    "compute_sharpe_ratio",
    "compute_sortino_ratio",
    "compute_win_rate",
    "generate_json",
    "generate_markdown",
]
