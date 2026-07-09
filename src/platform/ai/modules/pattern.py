"""Candlestick pattern classifier AI module.

Scans OHLC bars from the context for classic reversal and continuation
patterns (Doji, Hammer, Shooting Star, Bullish/Bearish Engulfing,
Morning/Evening Star) and emits a directional bias with a confidence
proportional to the strength of the detected patterns.
"""

from __future__ import annotations

from platform.ai.orchestrator import AIContext, AIModule, AIPrediction
from typing import Any


def _num(bar: dict[str, Any], key: str) -> float:
    try:
        return float(bar.get(key, 0))
    except (TypeError, ValueError):
        return 0.0


def detect_doji(bar: dict[str, Any]) -> bool:
    """Return True when a bar has a near-zero body (indecision)."""
    o, c, h, l = _num(bar, "open"), _num(bar, "close"), _num(bar, "high"), _num(bar, "low")
    return abs(c - o) / max(h - l, 1e-9) < 0.1


def detect_hammer(bar: dict[str, Any]) -> str | None:
    """Return 'hammer' (bullish) or 'shooting_star' (bearish) or None."""
    o, c, h, l = _num(bar, "open"), _num(bar, "close"), _num(bar, "high"), _num(bar, "low")
    body = abs(c - o)
    rng = max(h - l, 1e-9)
    upper, lower = h - max(o, c), min(o, c) - l
    if body / rng < 0.3 and lower > 2 * body:
        return "hammer"
    if body / rng < 0.3 and upper > 2 * body:
        return "shooting_star"
    return None


def detect_engulfing(prev: dict[str, Any], cur: dict[str, Any]) -> str | None:
    """Return 'bullish_engulfing' / 'bearish_engulfing' / None for two bars."""
    p_o, p_c = _num(prev, "open"), _num(prev, "close")
    c_o, c_c = _num(cur, "open"), _num(cur, "close")
    p_body, c_body = p_c - p_o, c_c - c_o
    if p_body < 0 and c_body > 0 and c_body > abs(p_body) and c_c >= p_o and c_o <= p_c:
        return "bullish_engulfing"
    if p_body > 0 and c_body < 0 and abs(c_body) > p_body and c_o >= p_c and c_c <= p_o:
        return "bearish_engulfing"
    return None


def detect_star(b1: dict[str, Any], b2: dict[str, Any], b3: dict[str, Any]) -> str | None:
    """Return 'morning_star' (bullish) or 'evening_star' (bearish) or None."""
    b1_o, b1_c = _num(b1, "open"), _num(b1, "close")
    b2_o, b2_c = _num(b2, "open"), _num(b2, "close")
    b3_o, b3_c = _num(b3, "open"), _num(b3, "close")
    b2_small = abs(b2_c - b2_o) < 0.5 * (abs(b1_c - b1_o) or 1e-9)
    if b1_c < b1_o and b2_small and b3_c > b3_o and b3_c > b1_o:
        return "morning_star"
    if b1_c > b1_o and b2_small and b3_c < b3_o and b3_c < b1_o:
        return "evening_star"
    return None


_BULLISH = {"hammer", "bullish_engulfing", "morning_star"}
_BEARISH = {"shooting_star", "bearish_engulfing", "evening_star"}
_PATTERN_STRENGTH = {
    "doji": 0.2,
    "hammer": 0.5,
    "shooting_star": 0.5,
    "bullish_engulfing": 0.7,
    "bearish_engulfing": 0.7,
    "morning_star": 0.85,
    "evening_star": 0.85,
}


class PatternAI(AIModule):
    """Candlestick pattern classifier.

    Reads `bars` (list of {open, high, low, close}) from ctx.features and
    inspects the most recent 1–3 bars for reversal patterns. Direction is
    determined by the net bullishness of the patterns found; confidence
    scales with the strongest pattern detected.
    """

    name = "pattern"
    version = "1.0.0"

    async def analyze(self, ctx: AIContext) -> AIPrediction:
        bars = ctx.features.get("bars", []) or []
        if len(bars) < 2:
            return AIPrediction(
                module=self.name,
                symbol=ctx.symbol,
                direction="neutral",
                confidence=0.2,
                horizon="short",
                payload={"patterns": [], "note": "insufficient bars"},
            )
        found: list[str] = []
        if detect_doji(bars[-1]):
            found.append("doji")
        hammer = detect_hammer(bars[-1])
        if hammer:
            found.append(hammer)
        eng = detect_engulfing(bars[-2], bars[-1])
        if eng:
            found.append(eng)
        if len(bars) >= 3:
            star = detect_star(bars[-3], bars[-2], bars[-1])
            if star:
                found.append(star)
        bull = sum(1 for p in found if p in _BULLISH)
        bear = sum(1 for p in found if p in _BEARISH)
        direction = "bullish" if bull > bear else "bearish" if bear > bull else "neutral"
        strength = max((_PATTERN_STRENGTH.get(p, 0.0) for p in found), default=0.0)
        confidence = min(1.0, strength + 0.1 * (len(found) - 1))
        return AIPrediction(
            module=self.name,
            symbol=ctx.symbol,
            direction=direction,
            confidence=confidence,
            horizon="short",
            payload={"patterns": found, "strength": round(strength, 3)},
        )
