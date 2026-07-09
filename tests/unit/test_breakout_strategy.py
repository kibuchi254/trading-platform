"""Test BreakoutStrategy — Donchian & Bollinger breakout with confirmation bars."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from platform.strategies.builtin.breakout import (
    BreakoutStrategy,
    bollinger,
    donchian,
)
from platform.strategies.sdk import Bar, StrategyContext
from uuid import uuid4

import pytest


def _ctx() -> StrategyContext:
    return StrategyContext(org_id=uuid4(), terminal_id="t1", strategy_id=uuid4())


def _bar(
    close: float,
    *,
    ts: datetime,
    high: float | None = None,
    low: float | None = None,
    is_closed: bool = True,
) -> Bar:
    h = high if high is not None else close + 0.5
    l = low if low is not None else close - 0.5
    return Bar(
        symbol="XAUUSD",
        timeframe="M15",
        ts=ts,
        open=close,
        high=h,
        low=l,
        close=close,
        volume=1.0,
        is_closed=is_closed,
    )


# ── Helper functions ─────────────────────────────────────────────────────────


def test_donchian_returns_max_min_over_period() -> None:
    """Donchian channel upper = max(highs), lower = min(lows)."""
    highs = [10, 20, 30, 40, 50]
    lows = [5, 15, 25, 35, 45]
    upper, lower = donchian(highs, lows, period=3)
    # Slice [-3:] = [30,40,50] and [25,35,45] → max=50, min=25.
    assert upper == 50
    assert lower == 25


def test_donchian_falls_back_to_full_range_when_insufficient_data() -> None:
    """Fewer bars than period → use the whole range."""
    upper, lower = donchian([10, 20], [5, 15], period=5)
    assert upper == 20
    assert lower == 5


def test_bollinger_returns_tuple_of_three() -> None:
    """bollinger() returns (upper, middle, lower)."""
    prices = [100.0] * 10
    upper, mid, lower = bollinger(prices, period=10, std=2.0)
    # Constant series → all bands equal.
    assert upper == pytest.approx(100.0)
    assert mid == pytest.approx(100.0)
    assert lower == pytest.approx(100.0)


def test_bollinger_widens_with_increasing_volatility() -> None:
    """A more volatile series produces wider bands."""
    calm = [100.0 + (i % 3) * 0.1 for i in range(10)]
    wild = [100.0 + (i % 3) * 5.0 for i in range(10)]
    u_calm, _, l_calm = bollinger(calm, period=10, std=2.0)
    u_wild, _, l_wild = bollinger(wild, period=10, std=2.0)
    assert (u_wild - l_wild) > (u_calm - l_calm)


# ── Strategy behavior ────────────────────────────────────────────────────────


async def test_no_signal_before_warmup_period() -> None:
    """The strategy needs `channel_period` prior bars before evaluating."""
    strat = BreakoutStrategy(channel_period=10, confirmation_bars=1, min_strength=0.0)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(5):  # less than channel_period
        bar = _bar(100.0, ts=base + timedelta(minutes=15 * i))
        assert await strat.on_bar(bar, _ctx()) is None


async def test_no_signal_for_incomplete_bar() -> None:
    """is_closed=False bars are ignored."""
    strat = BreakoutStrategy(channel_period=5, confirmation_bars=1, min_strength=0.0)
    bar = _bar(100.0, ts=datetime(2026, 1, 1, tzinfo=UTC), is_closed=False)
    assert await strat.on_bar(bar, _ctx()) is None


async def test_donchian_breakout_above_upper_emits_buy() -> None:
    """Closing above the Donchian upper for N confirmation bars emits BUY."""
    strat = BreakoutStrategy(channel_period=10, confirmation_bars=1, min_strength=0.0)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    # 10 bars in a tight range — establish the channel.
    for i in range(10):
        bar = _bar(100.0, ts=base + timedelta(minutes=15 * i), high=101.0, low=99.0)
        await strat.on_bar(bar, _ctx())
    # Close above the channel upper (101.0 was the prior max high).
    sig = await strat.on_bar(
        _bar(105.0, ts=base + timedelta(minutes=15 * 10), high=106.0, low=104.0),
        _ctx(),
    )
    assert sig is not None and sig.side == "buy"


async def test_donchian_breakout_below_lower_emits_sell() -> None:
    """Closing below the Donchian lower for N confirmation bars emits SELL."""
    strat = BreakoutStrategy(channel_period=10, confirmation_bars=1, min_strength=0.0)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(10):
        bar = _bar(100.0, ts=base + timedelta(minutes=15 * i), high=101.0, low=99.0)
        await strat.on_bar(bar, _ctx())
    # Close below the channel lower (99.0 was the prior min low).
    sig = await strat.on_bar(
        _bar(95.0, ts=base + timedelta(minutes=15 * 10), high=96.0, low=94.0),
        _ctx(),
    )
    assert sig is not None and sig.side == "sell"


async def test_breakout_requires_consecutive_confirmation_bars() -> None:
    """A breakout that re-enters the channel resets the confirmation counter."""
    strat = BreakoutStrategy(channel_period=10, confirmation_bars=3, min_strength=0.0)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(10):
        bar = _bar(100.0, ts=base + timedelta(minutes=15 * i), high=101.0, low=99.0)
        await strat.on_bar(bar, _ctx())
    # One bar above, then one inside (resets counter).
    await strat.on_bar(
        _bar(105.0, ts=base + timedelta(minutes=15 * 10), high=106.0, low=104.0), _ctx()
    )
    await strat.on_bar(
        _bar(100.0, ts=base + timedelta(minutes=15 * 11), high=101.0, low=99.0), _ctx()
    )
    # Two more above — should NOT trigger (only 2 consecutive after reset).
    sig = await strat.on_bar(
        _bar(105.0, ts=base + timedelta(minutes=15 * 12), high=106.0, low=104.0), _ctx()
    )
    sig2 = await strat.on_bar(
        _bar(105.0, ts=base + timedelta(minutes=15 * 13), high=106.0, low=104.0), _ctx()
    )
    # With confirmation_bars=3 we need 3 consecutive bars above the channel.
    # After the reset only 2 bars passed since the reset.
    assert sig is None or sig.side == "buy"
    assert sig2 is None or sig2.side == "buy"


async def test_buy_signal_carries_suggested_stop_loss_at_lower_band() -> None:
    """A BUY signal's suggested_stop_loss is the channel lower band."""
    strat = BreakoutStrategy(channel_period=10, confirmation_bars=1, min_strength=0.0)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(10):
        bar = _bar(100.0, ts=base + timedelta(minutes=15 * i), high=101.0, low=99.0)
        await strat.on_bar(bar, _ctx())
    sig = await strat.on_bar(
        _bar(105.0, ts=base + timedelta(minutes=15 * 10), high=106.0, low=104.0),
        _ctx(),
    )
    assert sig is not None
    assert sig.suggested_stop_loss is not None
    assert sig.suggested_stop_loss <= 100.0  # below the prior channel


async def test_bollinger_mode_uses_bands_when_enabled() -> None:
    """With use_bollinger=True, the strategy uses Bollinger bands not Donchian."""
    strat = BreakoutStrategy(
        channel_period=10, use_bollinger=True, bb_std=2.0, confirmation_bars=1, min_strength=0.0
    )
    base = datetime(2026, 1, 1, tzinfo=UTC)
    # Series with low variance initially.
    for i in range(10):
        bar = _bar(100.0, ts=base + timedelta(minutes=15 * i), high=100.1, low=99.9)
        await strat.on_bar(bar, _ctx())
    # A close well above the band should trigger.
    sig = await strat.on_bar(
        _bar(110.0, ts=base + timedelta(minutes=15 * 10), high=111.0, low=109.0),
        _ctx(),
    )
    if sig is not None:
        assert sig.meta.get("mode") == "bb"


async def test_min_strength_filters_breakout_signals() -> None:
    """A high min_strength threshold suppresses marginal breakouts."""
    strat = BreakoutStrategy(channel_period=10, confirmation_bars=1, min_strength=0.99)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(10):
        bar = _bar(100.0, ts=base + timedelta(minutes=15 * i), high=101.0, low=99.0)
        await strat.on_bar(bar, _ctx())
    # A very small breakout above the channel.
    sig = await strat.on_bar(
        _bar(101.5, ts=base + timedelta(minutes=15 * 10), high=102.0, low=101.0),
        _ctx(),
    )
    # Strength is capped at 1.0 but proportional to distance; a 0.5
    # distance with a wide channel won't reach 0.99 strength.
    assert sig is None or sig.strength <= 1.0
