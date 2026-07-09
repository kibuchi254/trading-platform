"""Test GridStrategy — alternating buy/sell signals on grid level crosses."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from platform.strategies.builtin.grid import GridStrategy
from platform.strategies.sdk import Bar, StrategyContext
from uuid import uuid4

import pytest


def _ctx() -> StrategyContext:
    return StrategyContext(org_id=uuid4(), terminal_id="t1", strategy_id=uuid4())


def _bar(close: float, *, ts: datetime, is_closed: bool = True) -> Bar:
    return Bar(
        symbol="XAUUSD",
        timeframe="M15",
        ts=ts,
        open=close,
        high=close + 0.5,
        low=close - 0.5,
        close=close,
        volume=1.0,
        is_closed=is_closed,
    )


# ── Anchor initialization ────────────────────────────────────────────────────


async def test_first_bar_sets_anchor_and_emits_no_signal() -> None:
    """The first closed bar anchors the grid; no signal is emitted yet."""
    strat = GridStrategy(grid_levels=5, grid_spacing_pct=0.01)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    sig = await strat.on_bar(_bar(1000.0, ts=base), _ctx())
    assert sig is None
    assert strat._anchor == 1000.0
    # Grid built with k = -5..+5 around anchor.
    assert len(strat._levels) == 11


async def test_incomplete_bar_does_not_anchor() -> None:
    """Bars with is_closed=False are ignored entirely."""
    strat = GridStrategy(grid_levels=5, grid_spacing_pct=0.01)
    bar = _bar(1000.0, ts=datetime(2026, 1, 1, tzinfo=UTC), is_closed=False)
    assert await strat.on_bar(bar, _ctx()) is None
    assert strat._anchor is None


# ── Grid level crossing ──────────────────────────────────────────────────────


async def test_crossing_upward_emits_sell() -> None:
    """A close above the anchor + 1 grid level triggers a SELL signal."""
    strat = GridStrategy(
        grid_levels=5, grid_spacing_pct=0.01, base_volume=0.01, take_profit_pct=0.003
    )
    base = datetime(2026, 1, 1, tzinfo=UTC)
    await strat.on_bar(_bar(1000.0, ts=base), _ctx())  # anchor
    # Move up one level (1%): close = 1010.0
    sig = await strat.on_bar(_bar(1010.0, ts=base + timedelta(minutes=15)), _ctx())
    assert sig is not None
    assert sig.side == "sell"
    assert sig.suggested_volume == pytest.approx(0.01)
    # Take-profit is set 0.3% below the grid level price.
    assert sig.suggested_take_profit is not None
    assert sig.suggested_take_profit < 1010.0


async def test_crossing_downward_emits_buy() -> None:
    """A close below the anchor - 1 grid level triggers a BUY signal."""
    strat = GridStrategy(
        grid_levels=5, grid_spacing_pct=0.01, base_volume=0.01, take_profit_pct=0.003
    )
    base = datetime(2026, 1, 1, tzinfo=UTC)
    await strat.on_bar(_bar(1000.0, ts=base), _ctx())  # anchor
    # Move down one level: close = 990.0
    sig = await strat.on_bar(_bar(990.0, ts=base + timedelta(minutes=15)), _ctx())
    assert sig is not None
    assert sig.side == "buy"
    assert sig.suggested_take_profit is not None
    assert sig.suggested_take_profit > 990.0


async def test_no_signal_when_price_stays_in_same_band() -> None:
    """A bar that doesn't cross into a new band emits nothing."""
    strat = GridStrategy(grid_levels=5, grid_spacing_pct=0.01)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    await strat.on_bar(_bar(1000.0, ts=base), _ctx())  # anchor at 1000
    # A small move that stays within the same band (no level crossed).
    sig = await strat.on_bar(
        _bar(1001.0, ts=base + timedelta(minutes=15)),
        _ctx(),
    )
    assert sig is None


async def test_already_filled_level_does_not_refire() -> None:
    """A grid level that has already fired is not re-fired on the same pass."""
    strat = GridStrategy(grid_levels=5, grid_spacing_pct=0.01)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    await strat.on_bar(_bar(1000.0, ts=base), _ctx())  # anchor
    # First crossing of level +1.
    sig1 = await strat.on_bar(
        _bar(1010.0, ts=base + timedelta(minutes=15)),
        _ctx(),
    )
    assert sig1 is not None and sig1.side == "sell"
    # Stay at 1010 — same band, no new crossing.
    sig2 = await strat.on_bar(
        _bar(1010.0, ts=base + timedelta(minutes=30)),
        _ctx(),
    )
    assert sig2 is None


async def test_opposite_level_unlocks_after_filling() -> None:
    """After firing level +k, level -k becomes eligible to fire again."""
    strat = GridStrategy(grid_levels=5, grid_spacing_pct=0.01)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    await strat.on_bar(_bar(1000.0, ts=base), _ctx())  # anchor
    # Fire level +1 (SELL).
    sig1 = await strat.on_bar(
        _bar(1010.0, ts=base + timedelta(minutes=15)),
        _ctx(),
    )
    assert sig1 is not None and sig1.side == "sell"
    # Drop to level -1 (BUY) — level +1 was filled, so -1 should unlock.
    sig2 = await strat.on_bar(
        _bar(990.0, ts=base + timedelta(minutes=30)),
        _ctx(),
    )
    assert sig2 is not None and sig2.side == "buy"


async def test_multi_level_cross_fires_only_once_per_bar() -> None:
    """Crossing multiple grid levels in one bar returns only ONE signal
    (the implementation returns after the first fresh level)."""
    strat = GridStrategy(grid_levels=5, grid_spacing_pct=0.01)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    await strat.on_bar(_bar(1000.0, ts=base), _ctx())  # anchor
    # Jump 3 levels up — should fire only one signal.
    sig = await strat.on_bar(
        _bar(1030.0, ts=base + timedelta(minutes=15)),
        _ctx(),
    )
    assert sig is not None and sig.side == "sell"


async def test_meta_carries_grid_level_and_anchor() -> None:
    """Signal meta includes the grid level index and the anchor price."""
    strat = GridStrategy(grid_levels=5, grid_spacing_pct=0.01)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    await strat.on_bar(_bar(1000.0, ts=base), _ctx())  # anchor
    sig = await strat.on_bar(
        _bar(1010.0, ts=base + timedelta(minutes=15)),
        _ctx(),
    )
    assert sig is not None
    assert "grid_level" in sig.meta
    assert sig.meta["grid_level"] == 1  # one level above anchor
    assert sig.meta["anchor"] == 1000.0


async def test_strength_constant_at_0_7() -> None:
    """All grid signals have strength 0.7 (per spec)."""
    strat = GridStrategy(grid_levels=5, grid_spacing_pct=0.01)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    await strat.on_bar(_bar(1000.0, ts=base), _ctx())  # anchor
    sig = await strat.on_bar(
        _bar(1010.0, ts=base + timedelta(minutes=15)),
        _ctx(),
    )
    assert sig is not None
    assert sig.strength == pytest.approx(0.7)


async def test_grid_level_clamped_at_max_index() -> None:
    """Price above the topmost level still fires (clamped to +grid_levels)."""
    strat = GridStrategy(grid_levels=3, grid_spacing_pct=0.01)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    await strat.on_bar(_bar(1000.0, ts=base), _ctx())  # anchor
    # Price way above the top level.
    sig = await strat.on_bar(
        _bar(1100.0, ts=base + timedelta(minutes=15)),
        _ctx(),
    )
    # Should emit a sell at the first fresh grid level (k=+1).
    assert sig is not None
    assert sig.side == "sell"
    assert sig.meta["grid_level"] == 1
