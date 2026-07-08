"""Backtesting subsystem."""
from platform.backtest.engine import BacktestConfig, BacktestEngine, BacktestResult
from platform.backtest.optimizer import OptimizationEngine, OptimizationResult, WalkForwardResult
from platform.backtest.metrics import (
    compute_equity_curve, compute_max_drawdown, compute_sharpe_ratio,
    compute_sortino_ratio, compute_profit_factor, compute_win_rate,
    compute_avg_trade_duration, compute_expectancy,
)
from platform.backtest.report import generate_markdown, generate_json

__all__ = [
    "BacktestEngine", "BacktestConfig", "BacktestResult",
    "OptimizationEngine", "OptimizationResult", "WalkForwardResult",
    "compute_equity_curve", "compute_max_drawdown", "compute_sharpe_ratio",
    "compute_sortino_ratio", "compute_profit_factor", "compute_win_rate",
    "compute_avg_trade_duration", "compute_expectancy",
    "generate_markdown", "generate_json",
]
