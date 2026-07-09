"""Backtest report generator — produces markdown + JSON summaries."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from platform.backtest.engine import BacktestResult


def generate_markdown(result: BacktestResult) -> str:
    """Generate a markdown report from a BacktestResult."""
    lines = [
        f"# Backtest Report — {result.backtest_id}",
        "",
        f"**Status:** {result.status}",
        f"**Generated at:** {datetime.now(UTC).isoformat()}",
        "",
        "## Summary Metrics",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Initial Capital | ${result.initial_capital:,.2f} |",
        f"| Final Equity | ${result.final_equital:,.2f} |",
        f"| Total Return | {result.total_return_pct:+.2f}% |",
        f"| Max Drawdown | {result.max_drawdown_pct:.2f}% |",
        f"| Sharpe Ratio | {result.sharpe:.3f} |",
        f"| Sortino Ratio | {result.sortino:.3f} |",
        f"| Win Rate | {result.win_rate * 100:.1f}% |",
        f"| Profit Factor | {result.profit_factor:.2f} |",
        f"| Total Trades | {result.total_trades} |",
        f"| Avg Duration | {result.avg_duration_seconds:.0f}s |",
        f"| Best Trade | ${result.best_trade:+.2f} |",
        f"| Worst Trade | ${result.worst_trade:+.2f} |",
        "",
    ]

    if result.error:
        lines += ["## Error", "", f"```\n{result.error}\n```", ""]

    # Equity curve ASCII chart
    if result.equity_curve:
        lines += ["## Equity Curve", "", "```", _ascii_chart(result.equity_curve), "```", ""]

    # Top 10 trades table
    if result.trades:
        lines += [
            "## Trades (first 10)",
            "",
            "| # | Symbol | Side | Volume | Entry | Exit | PnL |",
            "|---|--------|------|--------|-------|------|-----|",
        ]
        for i, t in enumerate(result.trades[:10], 1):
            lines.append(
                f"| {i} | {t.get('symbol', '')} | {t.get('side', '')} | "
                f"{t.get('volume', 0)} | {t.get('entry_price', 0):.5f} | "
                f"{t.get('exit_price', 0):.5f} | {float(t.get('pnl', 0)):+.2f} |"
            )
        lines.append("")

    return "\n".join(lines)


def generate_json(result: BacktestResult) -> str:
    """Generate a JSON report from a BacktestResult."""
    return json.dumps(result.model_dump(mode="json"), indent=2, default=str)


def _ascii_chart(equity_curve: list[dict], width: int = 60, height: int = 12) -> str:
    """Render a tiny ASCII chart of the equity curve."""
    if not equity_curve:
        return "(no data)"
    values = [e["equity"] for e in equity_curve]
    n = len(values)
    if n < 2:
        return f"single point: ${values[0]:.2f}"

    # Sample down to `width` points
    if n > width:
        step = n / width
        sampled = [values[int(i * step)] for i in range(width)]
    else:
        sampled = values

    lo, hi = min(sampled), max(sampled)
    rng = hi - lo if hi > lo else 1
    rows: list[str] = []
    for row in range(height, 0, -1):
        threshold = lo + (rng * row / height)
        line = ""
        for v in sampled:
            line += "█" if v >= threshold else " "
        rows.append(line)

    rows.append(f"low: ${lo:,.2f}    high: ${hi:,.2f}")
    return "\n".join(rows)


__all__ = ["generate_json", "generate_markdown"]
