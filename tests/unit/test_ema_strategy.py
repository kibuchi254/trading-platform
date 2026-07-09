"""Test the EMA cross strategy — verifies the SDK + example strategy work end-to-end."""

from __future__ import annotations

from datetime import UTC, datetime
from platform.strategies.builtin.ema_cross import EMACrossStrategy
from platform.strategies.sdk import Bar, StrategyContext
from uuid import uuid4


async def test_ema_cross_emits_buy_on_bullish_cross() -> None:
    strat = EMACrossStrategy(fast_period=3, slow_period=5, min_strength=0.0)
    ctx = StrategyContext(org_id=uuid4(), terminal_id="t1", strategy_id=uuid4())

    # Feed rising prices to trigger a bullish cross
    prices = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0]
    signals = []
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i, p in enumerate(prices):
        bar = Bar(
            symbol="XAUUSD",
            timeframe="M15",
            ts=base.replace(minute=i * 15),
            open=p,
            high=p + 0.5,
            low=p - 0.5,
            close=p,
            volume=1.0,
            is_closed=True,
        )
        sig = await strat.on_bar(bar, ctx)
        if sig is not None:
            signals.append(sig)
    assert any(s.side == "buy" for s in signals), "Expected at least one BUY signal"


async def test_ema_cross_no_signal_below_slow_period() -> None:
    strat = EMACrossStrategy(fast_period=9, slow_period=21)
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
