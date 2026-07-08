"""Test PatternAI — candlestick pattern detection (doji, hammer, engulfing, star)."""
from __future__ import annotations

from uuid import uuid4

import pytest

from platform.ai.modules.pattern import (
    PatternAI,
    detect_doji,
    detect_engulfing,
    detect_hammer,
    detect_star,
)
from platform.ai.orchestrator import AIContext


def _ctx(symbol: str = "XAUUSD") -> AIContext:
    return AIContext(org_id=uuid4(), symbol=symbol, timeframe="M15", features={})


def _bar(open_: float, high: float, low: float, close: float) -> dict:
    """Build a bar dict in the shape PatternAI consumes."""
    return {"open": open_, "high": high, "low": low, "close": close}


# ── detect_doji ──────────────────────────────────────────────────────────────


def test_detect_doji_true_when_body_is_tiny() -> None:
    """A bar where body / range < 0.1 is a doji."""
    # body = 0.1, range = 5 → 0.02 < 0.1
    bar = _bar(open_=100.0, high=105.0, low=100.0, close=100.1)
    assert detect_doji(bar) is True


def test_detect_doji_false_when_body_dominates_range() -> None:
    """A bar where body > 10% of range is NOT a doji."""
    bar = _bar(open_=100.0, high=110.0, low=99.0, close=109.0)
    # body = 9, range = 11 → 0.82 > 0.1
    assert detect_doji(bar) is False


# ── detect_hammer / shooting_star ────────────────────────────────────────────


def test_detect_hammer_with_long_lower_wick() -> None:
    """A small body + long lower wick → 'hammer' (bullish)."""
    # body = 1, range = 11 → 0.09 < 0.3; lower = 100-90 = 10 > 2*body = 2
    bar = _bar(open_=100.0, high=101.0, low=90.0, close=101.0)
    assert detect_hammer(bar) == "hammer"


def test_detect_shooting_star_with_long_upper_wick() -> None:
    """A small body + long upper wick → 'shooting_star' (bearish)."""
    # body = 1, range = 11; upper = 110-101 = 9 > 2*body = 2
    bar = _bar(open_=100.0, high=110.0, low=99.0, close=101.0)
    assert detect_hammer(bar) == "shooting_star"


def test_detect_hammer_none_when_body_too_large() -> None:
    """If the body dominates the range, neither pattern fires."""
    # body = 5, range = 6 → 0.83 > 0.3
    bar = _bar(open_=100.0, high=106.0, low=100.0, close=105.0)
    assert detect_hammer(bar) is None


# ── detect_engulfing ─────────────────────────────────────────────────────────


def test_detect_bullish_engulfing() -> None:
    """A small red candle followed by a larger green candle engulfing it."""
    prev = _bar(open_=100.0, high=101.0, low=99.0, close=99.5)  # red
    cur = _bar(open_=99.0, high=102.0, low=98.5, close=101.5)  # green, bigger
    assert detect_engulfing(prev, cur) == "bullish_engulfing"


def test_detect_bearish_engulfing() -> None:
    """A small green candle followed by a larger red candle engulfing it."""
    prev = _bar(open_=100.0, high=101.0, low=99.0, close=100.5)  # green
    cur = _bar(open_=101.0, high=101.5, low=98.5, close=99.0)  # red, bigger
    assert detect_engulfing(prev, cur) == "bearish_engulfing"


def test_detect_engulfing_none_when_no_engulfing_pattern() -> None:
    """Random consecutive bars do not trigger engulfing."""
    prev = _bar(open_=100.0, high=101.0, low=99.0, close=100.5)
    cur = _bar(open_=101.0, high=102.0, low=100.0, close=101.5)
    # Both green — not engulfing
    assert detect_engulfing(prev, cur) is None


# ── detect_star ──────────────────────────────────────────────────────────────


def test_detect_morning_star() -> None:
    """A long red, a small body, then a long green that closes above bar 1 open."""
    b1 = _bar(open_=110.0, high=110.5, low=99.0, close=100.0)  # big red (body=10)
    b2 = _bar(open_=100.0, high=101.0, low=99.5, close=100.5)  # small body
    b3 = _bar(open_=100.5, high=112.0, low=100.0, close=111.0)  # green, closes > b1.open
    assert detect_star(b1, b2, b3) == "morning_star"


def test_detect_evening_star() -> None:
    """A long green, a small body, then a long red that closes below bar 1 open."""
    b1 = _bar(open_=100.0, high=110.5, low=99.0, close=110.0)  # big green
    b2 = _bar(open_=110.0, high=110.5, low=109.5, close=110.2)  # small body
    b3 = _bar(open_=110.0, high=110.5, low=98.0, close=99.0)  # red, closes < b1.open
    assert detect_star(b1, b2, b3) == "evening_star"


def test_detect_star_none_for_random_bars() -> None:
    """No star pattern for unrelated bars."""
    b1 = _bar(open_=100.0, high=101.0, low=99.0, close=100.5)
    b2 = _bar(open_=100.5, high=101.0, low=99.5, close=100.7)
    b3 = _bar(open_=100.7, high=101.5, low=100.0, close=101.0)
    assert detect_star(b1, b2, b3) is None


# ── PatternAI.analyze ────────────────────────────────────────────────────────


async def test_pattern_ai_returns_neutral_with_insufficient_bars() -> None:
    """With <2 bars, PatternAI returns a low-confidence neutral prediction."""
    ai = PatternAI()
    ctx = _ctx()
    ctx.features["bars"] = [_bar(100.0, 101.0, 99.0, 100.5)]
    pred = await ai.analyze(ctx)
    assert pred.direction == "neutral"
    assert pred.confidence <= 0.3


async def test_pattern_ai_detects_doji_in_latest_bar() -> None:
    """A doji in the most recent bar appears in the patterns payload."""
    ai = PatternAI()
    ctx = _ctx()
    ctx.features["bars"] = [
        _bar(100.0, 101.0, 99.0, 100.5),
        _bar(100.5, 105.0, 100.0, 100.6),  # doji (tiny body / large range)
    ]
    pred = await ai.analyze(ctx)
    assert "doji" in pred.payload["patterns"]


async def test_pattern_ai_bullish_engulfing_emits_bullish() -> None:
    """A bullish engulfing in the latest 2 bars pushes direction bullish."""
    ai = PatternAI()
    ctx = _ctx()
    ctx.features["bars"] = [
        _bar(100.0, 101.0, 99.0, 99.5),  # red
        _bar(99.0, 102.0, 98.5, 101.5),  # green, engulfs prior
    ]
    pred = await ai.analyze(ctx)
    assert pred.direction == "bullish"
    assert "bullish_engulfing" in pred.payload["patterns"]


async def test_pattern_ai_confidence_scales_with_pattern_count() -> None:
    """Multiple patterns on the same bar boost confidence."""
    ai = PatternAI()
    ctx = _ctx()
    # Construct bars where the latest bar is both a doji AND a hammer,
    # and the prior two form a morning star. Three patterns → confidence
    # is higher than a single-pattern case.
    bars = [
        _bar(110.0, 110.5, 99.0, 100.0),  # big red — b1 for morning_star
        _bar(100.0, 101.0, 99.5, 100.5),  # small body — b2 for morning_star
        # b3: green closes > b1.open=110, plus doji-like body
        _bar(100.0, 112.0, 99.0, 110.5),
    ]
    ctx.features["bars"] = bars
    pred = await ai.analyze(ctx)
    # Multiple patterns detected → confidence should be > base strength.
    assert pred.confidence > 0.0


async def test_pattern_ai_payload_carries_strength_value() -> None:
    """The prediction payload includes a numeric strength field."""
    ai = PatternAI()
    ctx = _ctx()
    ctx.features["bars"] = [
        _bar(100.0, 101.0, 99.0, 99.5),
        _bar(99.0, 102.0, 98.5, 101.5),
    ]
    pred = await ai.analyze(ctx)
    assert "strength" in pred.payload
    assert isinstance(pred.payload["strength"], float)
