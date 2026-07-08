"""Test backtest metrics — pure functions, no I/O."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from platform.backtest.metrics import (
    compute_avg_trade_duration, compute_calibration, compute_equity_curve,
    compute_expectancy, compute_max_drawdown, compute_profit_factor,
    compute_sharpe_ratio, compute_sortino_ratio, compute_win_rate,
)


def test_empty_inputs_return_zero() -> None:
    assert compute_max_drawdown([]) == 0.0
    assert compute_sharpe_ratio([]) == 0.0
    assert compute_sortino_ratio([]) == 0.0
    assert compute_profit_factor([]) == 0.0
    assert compute_win_rate([]) == 0.0
    assert compute_avg_trade_duration([]) == 0.0
    assert compute_expectancy([]) == 0.0
    assert compute_equity_curve([], 1000) == []


def test_equity_curve_built_correctly() -> None:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    trades = [
        {"closed_at": base + timedelta(hours=1), "pnl": 100},
        {"closed_at": base + timedelta(hours=2), "pnl": -50},
        {"closed_at": base + timedelta(hours=3), "pnl": 200},
    ]
    curve = compute_equity_curve(trades, 1000)
    assert len(curve) == 4  # initial + 3 trades
    assert curve[0][1] == 1000
    assert curve[-1][1] == 1250  # 1000 + 100 - 50 + 200


def test_max_drawdown_computed_correctly() -> None:
    """Equity: 100 → 150 → 80 → 120 → 200. Peak=150, trough=80 → dd=-46.67%."""
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    curve = [
        (base, 100), (base + timedelta(hours=1), 150),
        (base + timedelta(hours=2), 80), (base + timedelta(hours=3), 120),
        (base + timedelta(hours=4), 200),
    ]
    dd = compute_max_drawdown(curve)
    assert dd < 0
    assert abs(dd - (-70 / 150)) < 1e-6  # -0.4667


def test_win_rate_all_wins() -> None:
    trades = [{"pnl": 10}, {"pnl": 20}, {"pnl": 5}]
    assert compute_win_rate(trades) == 1.0


def test_win_rate_mixed() -> None:
    trades = [{"pnl": 10}, {"pnl": -5}, {"pnl": 20}, {"pnl": -15}]
    assert compute_win_rate(trades) == 0.5


def test_profit_factor_inf_when_no_losses() -> None:
    trades = [{"pnl": 100}, {"pnl": 50}]
    assert compute_profit_factor(trades) == float("inf")


def test_profit_factor_finite() -> None:
    trades = [{"pnl": 100}, {"pnl": -50}, {"pnl": 200}, {"pnl": -100}]
    # gross_profit=300, gross_loss=150 → 2.0
    assert compute_profit_factor(trades) == pytest.approx(2.0)


def test_sharpe_positive_for_consistent_positive_returns() -> None:
    returns = [0.01, 0.011, 0.009, 0.010, 0.012, 0.010]
    sharpe = compute_sharpe_ratio(returns)
    assert sharpe > 0


def test_sortino_higher_than_sharpe_for_asymmetric_returns() -> None:
    """When upside volatility dominates, Sortino > Sharpe."""
    returns = [0.05, 0.01, 0.06, 0.02, 0.04]
    sharpe = compute_sharpe_ratio(returns)
    sortino = compute_sortino_ratio(returns)
    # Sortino only counts downside vol, which is zero here → inf
    assert sortino > sharpe


def test_expectancy_calculation() -> None:
    """6 trades: 4 wins avg $50, 2 losses avg $30. Expectancy = 50*0.667 - 30*0.333 = 23.33."""
    trades = [
        {"pnl": 50}, {"pnl": 50}, {"pnl": 50}, {"pnl": 50},
        {"pnl": -30}, {"pnl": -30},
    ]
    exp = compute_expectancy(trades)
    assert abs(exp - (50 * 4 / 6 - 30 * 2 / 6)) < 1e-6


def test_calibration_perfect() -> None:
    y_pred = ["bullish", "bearish", "neutral"]
    y_true = ["bullish", "bearish", "neutral"]
    assert compute_calibration(y_pred, y_true) == 1.0


def test_calibration_zero() -> None:
    y_pred = ["bullish", "bullish", "bullish"]
    y_true = ["bearish", "bearish", "bearish"]
    assert compute_calibration(y_pred, y_true) == 0.0


def test_avg_trade_duration_handles_none() -> None:
    trades = [{"duration_seconds": 60}, {"duration_seconds": None}, {"duration_seconds": 120}]
    # Only 2 valid → avg = 90
    assert compute_avg_trade_duration(trades) == 90
