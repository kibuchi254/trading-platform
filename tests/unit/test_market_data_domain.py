"""Test the market-data domain — Tick, OHLCBar, AggregatedBar, SymbolInfo."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from platform.core.exceptions import DomainError
from platform.domain.market_data import (
    AggregatedBar,
    OHLCBar,
    SymbolInfo,
    Tick,
    TimeframeBucket,
)
from platform.domain.shared import Timeframe

import pytest

# ── Tick value object ────────────────────────────────────────────────────────


def test_tick_mid_and_spread_computed_from_bid_ask() -> None:
    """mid = (bid+ask)/2; spread = ask-bid."""
    t = Tick(symbol="EURUSD", bid=1.0800, ask=1.0802)
    assert t.mid == pytest.approx(1.0801)
    assert t.spread == pytest.approx(0.0002)
    assert t.spread_pct == pytest.approx(0.0002 / 1.0801)


def test_tick_rejects_non_positive_prices() -> None:
    """bid/ask must both be positive."""
    with pytest.raises(DomainError):
        Tick(symbol="X", bid=0, ask=1)
    with pytest.raises(DomainError):
        Tick(symbol="X", bid=-1, ask=1)


def test_tick_rejects_inverted_quote() -> None:
    """bid must not exceed ask."""
    with pytest.raises(DomainError):
        Tick(symbol="X", bid=1.10, ask=1.08)


def test_tick_allows_optional_last_and_volume() -> None:
    """last/volume default to None for symbols that don't report them."""
    t = Tick(symbol="EURUSD", bid=1.08, ask=1.0801)
    assert t.last is None
    assert t.volume is None


# ── SymbolInfo value object ──────────────────────────────────────────────────


def test_symbol_info_point_derived_from_digits() -> None:
    """point = 10^(-digits)."""
    sym = SymbolInfo(name="EURUSD", digits=5)
    assert sym.point == pytest.approx(1e-5)
    sym3 = SymbolInfo(name="US30", digits=2)
    assert sym3.point == pytest.approx(1e-2)


def test_symbol_info_normalize_volume_snaps_to_step_grid() -> None:
    """Volumes are rounded to the nearest step and clamped to [min, max]."""
    sym = SymbolInfo(name="XAUUSD", digits=2, volume_min=0.01, volume_step=0.01, volume_max=10.0)
    assert sym.normalize_volume(0.137) == pytest.approx(0.14)
    assert sym.normalize_volume(0.001) == pytest.approx(0.01)  # clamp to min
    assert sym.normalize_volume(100.0) == pytest.approx(10.0)  # clamp to max


def test_symbol_info_rejects_zero_volume_step() -> None:
    """volume_step must be positive."""
    with pytest.raises(DomainError):
        SymbolInfo(name="X", volume_step=0)


def test_symbol_info_rejects_negative_digits() -> None:
    """digits cannot be negative."""
    with pytest.raises(DomainError):
        SymbolInfo(name="X", digits=-1)


# ── OHLCBar aggregate ────────────────────────────────────────────────────────


def _make_bar() -> OHLCBar:
    return OHLCBar(
        symbol="XAUUSD",
        timeframe=Timeframe(code="M1"),
        ts=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_ohlcbar_first_update_sets_ohlc_to_price() -> None:
    """The first update seeds open=high=low=close=price."""
    bar = _make_bar()
    bar.update(2000.0, volume=1.0)
    assert bar.open == 2000.0
    assert bar.high == 2000.0
    assert bar.low == 2000.0
    assert bar.close == 2000.0
    assert bar.volume == 1.0
    assert bar.tick_count == 1


def test_ohlcbar_subsequent_updates_extend_high_low() -> None:
    """Subsequent ticks update high/low/close, never open."""
    bar = _make_bar()
    bar.update(2000.0)
    bar.update(2010.0)
    bar.update(1995.0)
    bar.update(2005.0)
    assert bar.open == 2000.0
    assert bar.high == 2010.0
    assert bar.low == 1995.0
    assert bar.close == 2005.0
    assert bar.tick_count == 4


def test_ohlcbar_rejects_update_after_close() -> None:
    """A closed bar cannot be updated further."""
    bar = _make_bar()
    bar.update(2000.0)
    bar.close_bar()
    with pytest.raises(DomainError):
        bar.update(2010.0)


def test_ohlcbar_rejects_update_with_non_positive_price() -> None:
    """Prices must be positive."""
    bar = _make_bar()
    with pytest.raises(DomainError):
        bar.update(0)
    with pytest.raises(DomainError):
        bar.update(-5)


def test_ohlcbar_close_empty_bar_raises() -> None:
    """Closing a bar with no ticks is a DomainError."""
    bar = _make_bar()
    with pytest.raises(DomainError):
        bar.close_bar()


def test_ohlcbar_close_emits_bar_closed_event() -> None:
    """close_bar freezes the bar and emits BarClosed."""
    bar = _make_bar()
    bar.update(2000.0)
    bar.update(2010.0)
    bar.close_bar()
    assert bar.is_closed is True
    events = bar.collect_events()
    assert any(e.__class__.__name__ == "BarClosed" for e in events)


# ── AggregatedBar aggregate ──────────────────────────────────────────────────


def test_aggregated_bar_first_tick_creates_current_bar() -> None:
    """The first tick opens a fresh current_bar."""
    agg = AggregatedBar(
        bucket=TimeframeBucket(
            symbol="XAUUSD",
            timeframe=Timeframe(code="M1"),
            bucket_start=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    tick = Tick(
        symbol="XAUUSD", bid=2000.0, ask=2000.5, ts=datetime(2026, 1, 1, 0, 0, 5, tzinfo=UTC)
    )
    current, closed = agg.ingest(tick)
    assert current is not None
    assert current.open == pytest.approx(2000.25)
    assert closed is None


def test_aggregated_bar_rolls_when_bucket_boundary_crossed() -> None:
    """Crossing into a new timeframe bucket closes the old bar."""
    bucket_start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    agg = AggregatedBar(
        bucket=TimeframeBucket(
            symbol="XAUUSD",
            timeframe=Timeframe(code="M1"),
            bucket_start=bucket_start,
        )
    )
    # First tick inside the first minute bucket.
    agg.ingest(
        Tick(symbol="XAUUSD", bid=2000.0, ask=2000.5, ts=bucket_start + timedelta(seconds=10))
    )
    # Second tick in the NEXT minute bucket — triggers a roll.
    next_ts = bucket_start + timedelta(minutes=1, seconds=5)
    current, closed = agg.ingest(Tick(symbol="XAUUSD", bid=2010.0, ask=2010.5, ts=next_ts))
    assert closed is not None, "Expected previous bar to be closed on roll"
    assert closed.is_closed is True
    assert agg.last_closed_bar is closed
    assert current.open == pytest.approx(2010.25)


def test_aggregated_bar_rejects_tick_with_wrong_symbol() -> None:
    """Ticks whose symbol does not match the bucket are rejected."""
    agg = AggregatedBar(
        bucket=TimeframeBucket(
            symbol="XAUUSD",
            timeframe=Timeframe(code="M1"),
            bucket_start=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    tick = Tick(symbol="EURUSD", bid=1.08, ask=1.0801, ts=datetime(2026, 1, 1, 0, 0, 5, tzinfo=UTC))
    with pytest.raises(DomainError):
        agg.ingest(tick)


def test_aggregated_bar_multiple_ticks_in_same_bucket_accumulate() -> None:
    """Several ticks within the same bucket extend a single bar."""
    bucket_start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    agg = AggregatedBar(
        bucket=TimeframeBucket(
            symbol="XAUUSD",
            timeframe=Timeframe(code="M1"),
            bucket_start=bucket_start,
        )
    )
    # bar.update receives tick.mid (= (bid+ask)/2), so the expected highs
    # and lows are the mid prices.
    mids = [2000.25, 2010.25, 1995.25, 2005.25]
    for i, p in enumerate([2000.0, 2010.0, 1995.0, 2005.0]):
        agg.ingest(
            Tick(symbol="XAUUSD", bid=p, ask=p + 0.5, ts=bucket_start + timedelta(seconds=10 * i))
        )
    assert agg.current_bar is not None
    assert agg.current_bar.tick_count == 4
    assert agg.current_bar.high == pytest.approx(max(mids))
    assert agg.current_bar.low == pytest.approx(min(mids))
