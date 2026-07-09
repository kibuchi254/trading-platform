"""Test PositionSizeAI — Kelly fraction computation and cap application."""

from __future__ import annotations

from platform.ai.modules.position_size import (
    PositionSizeAI,
    cap_kelly,
    kelly_fraction,
)
from platform.ai.orchestrator import AIContext
from uuid import uuid4

import pytest


def _ctx(features: dict | None = None) -> AIContext:
    return AIContext(
        org_id=uuid4(),
        symbol="XAUUSD",
        timeframe="M15",
        features=features or {},
    )


# ── kelly_fraction helper ────────────────────────────────────────────────────


def test_kelly_zero_for_no_edge() -> None:
    """win_rate=0.5 with equal avg_win/avg_loss gives f=0."""
    f = kelly_fraction(0.5, avg_win=1.0, avg_loss=1.0)
    # p*b - q = 0.5*1 - 0.5 = 0; f = 0/b = 0
    assert f == pytest.approx(0.0)


def test_kelly_positive_for_favorable_edge() -> None:
    """A high win-rate with positive payoff yields a positive Kelly fraction."""
    f = kelly_fraction(0.6, avg_win=2.0, avg_loss=1.0)
    # p*b - q = 0.6*2 - 0.4 = 0.8; f = 0.8/2 = 0.4
    assert f == pytest.approx(0.4)


def test_kelly_zero_for_zero_avg_win() -> None:
    """avg_win=0 → degenerate → 0.0."""
    assert kelly_fraction(0.7, avg_win=0.0, avg_loss=1.0) == 0.0


def test_kelly_zero_for_zero_avg_loss() -> None:
    """avg_loss=0 → degenerate → 0.0 (avoid divide-by-zero)."""
    assert kelly_fraction(0.7, avg_win=1.0, avg_loss=0.0) == 0.0


def test_kelly_clamps_negative_to_zero() -> None:
    """Negative edge (more losing than winning) → 0.0, not negative."""
    f = kelly_fraction(0.3, avg_win=1.0, avg_loss=2.0)
    # p*b - q = 0.3*0.5 - 0.7 = -0.55; f = -0.55/0.5 = -1.1 → clamped to 0
    assert f == 0.0


# ── cap_kelly helper ─────────────────────────────────────────────────────────


def test_cap_kelly_applies_fractional_cap() -> None:
    """cap_kelly(f, cap) = min(f*cap, cap)."""
    # Full Kelly = 0.4, cap = 0.25 → 0.4 * 0.25 = 0.1 (less than cap)
    assert cap_kelly(0.4, cap=0.25) == pytest.approx(0.1)


def test_cap_kelly_caps_at_max_when_full_kelly_exceeds_cap() -> None:
    """Even a huge Kelly cannot exceed the cap."""
    # Full Kelly = 2.0 (extremely favorable), cap = 0.25 → 0.5 capped to 0.25
    assert cap_kelly(2.0, cap=0.25) == pytest.approx(0.25)


def test_cap_kelly_zero_for_zero_kelly() -> None:
    """No edge → 0.0 regardless of cap."""
    assert cap_kelly(0.0, cap=0.25) == 0.0


def test_cap_kelly_zero_for_negative_kelly() -> None:
    """Negative Kelly (clamped upstream) → 0.0."""
    assert cap_kelly(-0.5, cap=0.25) == 0.0


# ── PositionSizeAI.analyze ───────────────────────────────────────────────────


async def test_position_size_ai_returns_neutral_for_no_equity() -> None:
    """equity ≤ 0 → low-confidence neutral prediction with error payload."""
    ai = PositionSizeAI()
    ctx = _ctx({"equity": 0.0})
    pred = await ai.analyze(ctx)
    assert pred.direction == "neutral"
    assert pred.payload.get("error") == "no equity"


async def test_position_size_ai_returns_bullish_with_edge() -> None:
    """A positive Kelly edge yields bullish direction."""
    ai = PositionSizeAI()
    ctx = _ctx(
        {
            "win_rate": 0.6,
            "avg_win": 2.0,
            "avg_loss": 1.0,
            "equity": 10_000.0,
            "max_drawdown_cap": 0.25,
            "stop_distance": 0.01,
        }
    )
    pred = await ai.analyze(ctx)
    assert pred.direction == "bullish"
    assert pred.payload["kelly_fraction"] == pytest.approx(0.4)


async def test_position_size_ai_caps_kelly_fraction() -> None:
    """The capped fraction never exceeds max_drawdown_cap."""
    ai = PositionSizeAI()
    ctx = _ctx(
        {
            # Extreme edge → full Kelly > 1.
            "win_rate": 0.95,
            "avg_win": 10.0,
            "avg_loss": 1.0,
            "equity": 10_000.0,
            "max_drawdown_cap": 0.25,
            "stop_distance": 0.01,
        }
    )
    pred = await ai.analyze(ctx)
    assert pred.payload["capped_fraction"] <= 0.25


async def test_position_size_ai_suggested_volume_uses_stop_distance() -> None:
    """suggested_volume = (equity * capped_fraction) / (equity * stop_distance)."""
    ai = PositionSizeAI()
    ctx = _ctx(
        {
            "win_rate": 0.6,
            "avg_win": 2.0,
            "avg_loss": 1.0,
            "equity": 10_000.0,
            "max_drawdown_cap": 0.25,
            "stop_distance": 0.02,
        }
    )
    pred = await ai.analyze(ctx)
    # capped = 0.4 * 0.25 = 0.1; risk_per_trade = 10000 * 0.1 = 1000
    # suggested_volume = 1000 / (10000 * 0.02) = 1000 / 200 = 5.0
    assert pred.payload["suggested_volume"] == pytest.approx(5.0)
    assert pred.payload["risk_per_trade"] == pytest.approx(1000.0)


async def test_position_size_ai_payload_includes_payoff_ratio() -> None:
    """The payload reports the win_rate and payoff ratio."""
    ai = PositionSizeAI()
    ctx = _ctx(
        {
            "win_rate": 0.55,
            "avg_win": 1.5,
            "avg_loss": 1.0,
            "equity": 10_000.0,
            "max_drawdown_cap": 0.25,
            "stop_distance": 0.01,
        }
    )
    pred = await ai.analyze(ctx)
    assert pred.payload["win_rate"] == pytest.approx(0.55)
    assert pred.payload["payoff_ratio"] == pytest.approx(1.5)


async def test_position_size_ai_neutral_when_kelly_is_zero() -> None:
    """No edge (kelly=0) → neutral direction."""
    ai = PositionSizeAI()
    ctx = _ctx(
        {
            "win_rate": 0.5,
            "avg_win": 1.0,
            "avg_loss": 1.0,
            "equity": 10_000.0,
            "max_drawdown_cap": 0.25,
            "stop_distance": 0.01,
        }
    )
    pred = await ai.analyze(ctx)
    assert pred.direction == "neutral"
    assert pred.payload["capped_fraction"] == 0.0
