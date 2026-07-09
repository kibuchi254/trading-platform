"""Backtest performance metrics — pure functions, no I/O.

All functions handle empty inputs gracefully (return 0.0) so callers can
compute metrics on partial results without defensive try/except.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime


def compute_equity_curve(
    trades: list[dict],
    initial_capital: float,
) -> list[tuple[datetime, float]]:
    """Build (timestamp, equity) pairs from a list of closed trades.

    Each trade dict should have `closed_at` (datetime) and `pnl` (float).
    """
    if not trades:
        return []
    sorted_trades = sorted(trades, key=lambda t: t["closed_at"])
    curve: list[tuple[datetime, float]] = [(sorted_trades[0]["closed_at"], initial_capital)]
    equity = initial_capital
    for t in sorted_trades:
        equity += float(t.get("pnl", 0))
        curve.append((t["closed_at"], equity))
    return curve


def compute_drawdown_series(
    equity_curve: list[tuple[datetime, float]],
) -> list[tuple[datetime, float]]:
    """Return (timestamp, drawdown_fraction) pairs. Drawdown is negative."""
    if not equity_curve:
        return []
    peak = equity_curve[0][1]
    out: list[tuple[datetime, float]] = []
    for ts, eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (eq - peak) / peak if peak > 0 else 0.0
        out.append((ts, dd))
    return out


def compute_max_drawdown(equity_curve: list[tuple[datetime, float]]) -> float:
    """Max drawdown as a negative fraction (e.g. -0.15 = -15%)."""
    if not equity_curve:
        return 0.0
    peak = equity_curve[0][1]
    max_dd = 0.0
    for _, eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (eq - peak) / peak if peak > 0 else 0.0
        if dd < max_dd:
            max_dd = dd
    return max_dd


def compute_returns(equity_curve: list[tuple[datetime, float]]) -> list[float]:
    """Period-over-period returns from the equity curve."""
    if len(equity_curve) < 2:
        return []
    out: list[float] = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1][1]
        cur = equity_curve[i][1]
        if prev <= 0:
            out.append(0.0)
        else:
            out.append((cur - prev) / prev)
    return out


def compute_sharpe_ratio(
    returns: Sequence[float],
    periods_per_year: int = 252,
    rf: float = 0.0,
) -> float:
    """Annualized Sharpe ratio. `rf` is the risk-free rate per period."""
    if len(returns) < 2:
        return 0.0
    excess = [r - rf for r in returns]
    mean = sum(excess) / len(excess)
    var = sum((r - mean) ** 2 for r in excess) / (len(excess) - 1)
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(periods_per_year)


def compute_sortino_ratio(
    returns: Sequence[float],
    periods_per_year: int = 252,
    rf: float = 0.0,
) -> float:
    """Annualized Sortino ratio (only penalizes downside volatility)."""
    if len(returns) < 2:
        return 0.0
    excess = [r - rf for r in returns]
    mean = sum(excess) / len(excess)
    downside = [r for r in excess if r < 0]
    if not downside:
        return float("inf") if mean > 0 else 0.0
    downside_var = sum(r**2 for r in downside) / len(downside)
    downside_std = math.sqrt(downside_var)
    if downside_std == 0:
        return 0.0
    return (mean / downside_std) * math.sqrt(periods_per_year)


def compute_profit_factor(trades: list[dict]) -> float:
    """Gross profit / gross loss (absolute). 0.0 if no losing trades."""
    if not trades:
        return 0.0
    gross_profit = sum(float(t.get("pnl", 0)) for t in trades if float(t.get("pnl", 0)) > 0)
    gross_loss = abs(sum(float(t.get("pnl", 0)) for t in trades if float(t.get("pnl", 0)) < 0))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def compute_win_rate(trades: list[dict]) -> float:
    """Fraction of trades with positive PnL."""
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if float(t.get("pnl", 0)) > 0)
    return wins / len(trades)


def compute_avg_trade_duration(trades: list[dict]) -> float:
    """Average trade duration in seconds."""
    if not trades:
        return 0.0
    durations = [
        t.get("duration_seconds", 0) for t in trades if t.get("duration_seconds") is not None
    ]
    if not durations:
        return 0.0
    return sum(durations) / len(durations)


def compute_expectancy(trades: list[dict]) -> float:
    """Expected PnL per trade = avg_win * win_rate - avg_loss * loss_rate."""
    if not trades:
        return 0.0
    pnls = [float(t.get("pnl", 0)) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [abs(p) for p in pnls if p < 0]
    win_rate = len(wins) / len(pnls)
    loss_rate = len(losses) / len(pnls)
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    return avg_win * win_rate - avg_loss * loss_rate


def compute_calibration(y_pred: list[str], y_true: list[str]) -> float:
    """Classification accuracy for AI predictions."""
    if not y_pred or len(y_pred) != len(y_true):
        return 0.0
    correct = sum(1 for p, t in zip(y_pred, y_true) if p == t)
    return correct / len(y_pred)


def compute_risk_adjusted_return(
    returns: Sequence[float],
    risk_free: float = 0.0,
) -> float:
    """Simple return / volatility, not annualized."""
    if len(returns) < 2:
        return 0.0
    excess = [r - risk_free for r in returns]
    mean = sum(excess) / len(excess)
    var = sum((r - mean) ** 2 for r in excess) / (len(excess) - 1)
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    return mean / std


def compute_cagr(initial: float, final: float, days: int) -> float:
    """Compound Annual Growth Rate."""
    if initial <= 0 or days <= 0:
        return 0.0
    return (final / initial) ** (365.0 / days) - 1.0


def compute_volatility(returns: Sequence[float], periods_per_year: int = 252) -> float:
    """Annualized standard deviation of returns."""
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(var) * math.sqrt(periods_per_year)


__all__ = [
    "compute_avg_trade_duration",
    "compute_cagr",
    "compute_calibration",
    "compute_drawdown_series",
    "compute_equity_curve",
    "compute_expectancy",
    "compute_max_drawdown",
    "compute_profit_factor",
    "compute_returns",
    "compute_risk_adjusted_return",
    "compute_sharpe_ratio",
    "compute_sortino_ratio",
    "compute_volatility",
    "compute_win_rate",
]
