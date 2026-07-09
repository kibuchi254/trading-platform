"""Volatility regime classifier AI module (GARCH-inspired heuristics).

Computes a realized volatility figure from a return series and maps it
into one of four regimes: LOW / NORMAL / HIGH / EXTREME. EXTREME regimes
carry a bearish bias because they typically coincide with liquidity
withdrawals, gap risk, and deleveraging.
"""

from __future__ import annotations

import statistics
from platform.ai.orchestrator import AIContext, AIModule, AIPrediction


def realized_vol(returns: list[float], window: int = 20) -> float:
    """Population standard deviation of the last `window` returns.

    Accepts returns expressed either as fractions (0.01 = 1%) or as
    percentage points (1.0 = 1%); callers should normalize the result
    consistently (see _as_pct).
    """
    if not returns:
        return 0.0
    sample = returns[-window:]
    if len(sample) < 2:
        return 0.0
    return statistics.pstdev(sample)


def _atr_like(returns: list[float], window: int = 14) -> float:
    """ATR-proxy: mean absolute return over the trailing window."""
    if not returns:
        return 0.0
    sample = returns[-window:]
    return sum(abs(r) for r in sample) / len(sample)


def _as_pct(vol: float) -> float:
    """Normalize a volatility figure to a percentage (1.0 == 1%)."""
    return vol * 100.0 if vol < 1.0 else vol


def _classify(vol_pct: float) -> tuple[str, float]:
    """Map daily vol % to (regime, suggested_size_factor)."""
    if vol_pct < 0.5:
        return "LOW", 1.25
    if vol_pct < 1.5:
        return "NORMAL", 1.0
    if vol_pct < 3.0:
        return "HIGH", 0.6
    return "EXTREME", 0.3


class VolatilityAI(AIModule):
    """GARCH-style volatility regime classifier.

    Reads `returns` (list of % returns) from ctx.features. Computes
    realized volatility and an ATR-like measure, then classifies the
    regime. EXTREME and HIGH regimes tilt bearish; LOW/NORMAL are
    neutral. The payload carries the regime, vol percentage, and a
    suggested position-size multiplier for the risk engine.
    """

    name = "volatility"
    version = "1.0.0"

    async def analyze(self, ctx: AIContext) -> AIPrediction:
        returns = ctx.features.get("returns", []) or []
        if not returns:
            return AIPrediction(
                module=self.name,
                symbol=ctx.symbol,
                direction="neutral",
                confidence=0.1,
                horizon="short",
                payload={"regime": "UNKNOWN", "vol_pct": 0.0, "suggested_size_factor": 1.0},
            )
        vol = realized_vol(returns, window=20)
        vol_pct = _as_pct(vol)
        atr_pct = _as_pct(_atr_like(returns, window=14))
        regime, size_factor = _classify(vol_pct)
        if regime == "EXTREME":
            direction = "bearish"
            confidence = min(1.0, vol_pct / 5.0)
        elif regime == "HIGH":
            direction = "bearish"
            confidence = min(0.6, vol_pct / 5.0)
        else:
            direction = "neutral"
            confidence = 0.4
        return AIPrediction(
            module=self.name,
            symbol=ctx.symbol,
            direction=direction,
            confidence=confidence,
            horizon="short",
            payload={
                "regime": regime,
                "vol_pct": round(vol_pct, 3),
                "atr_pct": round(atr_pct, 3),
                "suggested_size_factor": size_factor,
            },
        )
