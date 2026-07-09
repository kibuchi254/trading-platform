"""Post-trade execution quality scorer AI module.

Reviews recently executed trades and scores them on three dimensions:
slippage (entry vs requested price, normalized by ATR), timing (entry
timestamp vs optimal execution window), and size appropriateness
(actual vs ideal volume). Emits an overall score and per-trade
recommendations for routing and sizing improvements.
"""

from __future__ import annotations

from platform.ai.orchestrator import AIContext, AIModule, AIPrediction
from typing import Any


def score_slippage(requested: float, actual: float, atr: float) -> float:
    """Score slippage in [0, 1]; 1 = no slippage, 0 = ≥ 1 ATR of slip."""
    if atr <= 0:
        return 1.0 if requested == actual else 0.5
    slip = abs(actual - requested)
    ratio = slip / atr
    return max(0.0, 1.0 - ratio)


def score_timing(entry_ts: float, optimal_window: tuple[float, float]) -> float:
    """Score timing in [0, 1]; 1 = inside window, 0 = far outside."""
    lo, hi = optimal_window
    if lo <= entry_ts <= hi:
        return 1.0
    span = max(hi - lo, 1e-9)
    dist = lo - entry_ts if entry_ts < lo else entry_ts - hi
    return max(0.0, 1.0 - dist / span)


def _score_size(requested_size: float, optimal_size: float) -> float:
    """Score size appropriateness in [0, 1]; 1 = exact match."""
    if optimal_size <= 0:
        return 0.5
    ratio = requested_size / optimal_size
    return max(0.0, 1.0 - abs(ratio - 1.0))


def _f(d: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(d.get(key, default))
    except (TypeError, ValueError):
        return default


class TradeQualityAI(AIModule):
    """Post-trade execution quality scorer.

    Reads `recent_trades` (list of dicts with entry/requested price, ATR,
    entry_ts, optimal window, volume, optimal_volume) from ctx.features.
    Returns an overall score (0–1) plus breakdowns and recommendations.
    Direction is always neutral; confidence mirrors the overall score.
    """

    name = "trade_quality"
    version = "1.0.0"

    async def analyze(self, ctx: AIContext) -> AIPrediction:
        trades = ctx.features.get("recent_trades", []) or []
        if not trades:
            return AIPrediction(
                module=self.name,
                symbol=ctx.symbol,
                direction="neutral",
                confidence=0.1,
                horizon="short",
                payload={
                    "overall_score": 0.0,
                    "slippage_score": 0.0,
                    "timing_score": 0.0,
                    "recommendations": [],
                },
            )
        slip_scores: list[float] = []
        time_scores: list[float] = []
        size_scores: list[float] = []
        recommendations: list[str] = []
        for i, t in enumerate(trades):
            atr = _f(t, "atr", _f(t, "spread", 0.0)) or 1e-9
            s_slip = score_slippage(
                _f(t, "requested_price", _f(t, "requested")),
                _f(t, "entry_price", _f(t, "actual")),
                atr,
            )
            s_time = score_timing(
                _f(t, "entry_ts"),
                (_f(t, "window_start"), _f(t, "window_end")),
            )
            s_size = _score_size(
                _f(t, "volume"),
                _f(t, "optimal_volume", _f(t, "requested_volume")),
            )
            slip_scores.append(s_slip)
            time_scores.append(s_time)
            size_scores.append(s_size)
            if s_slip < 0.7:
                recommendations.append(f"Trade {i}: high slippage — review order routing")
            if s_time < 0.7:
                recommendations.append(f"Trade {i}: suboptimal timing — tighten trigger")
            if s_size < 0.7:
                recommendations.append(f"Trade {i}: size mismatch — recalibrate sizer")
        n = len(trades)
        avg_slip = sum(slip_scores) / n
        avg_time = sum(time_scores) / n
        avg_size = sum(size_scores) / n
        overall = 0.4 * avg_slip + 0.35 * avg_time + 0.25 * avg_size
        if not recommendations:
            recommendations.append("Execution quality is within tolerance")
        return AIPrediction(
            module=self.name,
            symbol=ctx.symbol,
            direction="neutral",
            confidence=min(1.0, overall),
            horizon="short",
            payload={
                "overall_score": round(overall, 3),
                "slippage_score": round(avg_slip, 3),
                "timing_score": round(avg_time, 3),
                "size_score": round(avg_size, 3),
                "recommendations": recommendations,
            },
        )
