"""Test RSI reversion strategy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from platform.strategies.builtin.rsi_reversion import RSIReversionStrategy
from platform.strategies.sdk import Bar, StrategyContext
from uuid import uuid4


async def test_no_signal_with_insufficient_data() -> None:
    strat = RSIReversionStrategy(period=14, oversold=30, overbought=70, min_strength=0.0)
    ctx = StrategyContext(org_id=uuid4(), terminal_id="t1", strategy_id=uuid4())
    bar = Bar(
        symbol="XAUUSD",
        timeframe="M15",
        ts=datetime.now(UTC),
        open=100,
        high=101,
        low=99,
        close=100,
        volume=1.0,
        is_closed=True,
    )
    assert await strat.on_bar(bar, ctx) is None


async def test_emits_buy_on_oversold_recovery() -> None:
    """Feed prices that drop into oversold then recover."""
    strat = RSIReversionStrategy(period=5, oversold=30, overbought=70, min_strength=0.0)
    ctx = StrategyContext(org_id=uuid4(), terminal_id="t1", strategy_id=uuid4())
    base = datetime(2026, 1, 1, tzinfo=UTC)

    # Sharp drop to push RSI into oversold
    prices = [100, 95, 90, 85, 80, 78, 76]
    for i, p in enumerate(prices):
        bar = Bar(
            symbol="XAUUSD",
            timeframe="M15",
            ts=base + timedelta(minutes=i * 15),
            open=p,
            high=p + 1,
            low=p - 1,
            close=p,
            volume=1.0,
            is_closed=True,
        )
        await strat.on_bar(bar, ctx)

    # Recovery — RSI should cross back above 30
    signals = []
    for i, p in enumerate([78, 82, 86, 90], start=len(prices)):
        bar = Bar(
            symbol="XAUUSD",
            timeframe="M15",
            ts=base + timedelta(minutes=i * 15),
            open=p,
            high=p + 1,
            low=p - 1,
            close=p,
            volume=1.0,
            is_closed=True,
        )
        sig = await strat.on_bar(bar, ctx)
        if sig is not None:
            signals.append(sig)

    assert any(s.side == "buy" for s in signals), (
        "Expected at least one BUY signal on oversold recovery"
    )
