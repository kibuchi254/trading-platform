"""Kelly criterion position sizer AI module.

Computes the full Kelly fraction from a strategy's win rate and the
ratio of average win to average loss, then applies a fractional cap
(default quarter-Kelly) to dampen drawdown variance. Translates the
capped fraction into a per-trade risk budget and a suggested volume
assuming a configurable stop distance.
"""
from __future__ import annotations

from platform.ai.orchestrator import AIContext, AIModule, AIPrediction


def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Full Kelly fraction: f = (p*b - q) / b, where b = avg_win/avg_loss.

    Returns 0.0 when inputs are degenerate (no edge or impossible ratio).
    """
    if avg_win <= 0 or avg_loss <= 0:
        return 0.0
    p = max(0.0, min(1.0, float(win_rate)))
    q = 1.0 - p
    b = avg_win / avg_loss
    if b <= 0:
        return 0.0
    f = (p * b - q) / b
    return max(0.0, f)


def cap_kelly(f: float, cap: float = 0.25) -> float:
    """Apply a fractional Kelly cap (default quarter-Kelly = 0.25)."""
    return max(0.0, min(f * cap, cap))


class PositionSizeAI(AIModule):
    """Kelly criterion position sizer.

    Pulls `win_rate`, `avg_win`, `avg_loss`, `equity`, `max_drawdown_cap`
    and an optional `stop_distance` from ctx.features. Computes the full
    Kelly fraction, applies the fractional cap, and emits the capped
    fraction, a per-trade risk budget, and a suggested volume. Direction
    is bullish when a positive Kelly edge exists, neutral otherwise.
    """
    name = "position_size"
    version = "1.0.0"

    async def analyze(self, ctx: AIContext) -> AIPrediction:
        win_rate = float(ctx.features.get("win_rate", 0.5))
        avg_win = float(ctx.features.get("avg_win", 0.0))
        avg_loss = float(ctx.features.get("avg_loss", 0.0))
        equity = float(ctx.features.get("equity", 0.0))
        cap = float(ctx.features.get("max_drawdown_cap", 0.25))
        stop_distance = max(float(ctx.features.get("stop_distance", 0.01)), 1e-9)
        if equity <= 0:
            return AIPrediction(
                module=self.name, symbol=ctx.symbol, direction="neutral",
                confidence=0.1, horizon="short",
                payload={"kelly_fraction": 0.0, "capped_fraction": 0.0,
                         "suggested_volume": 0.0, "risk_per_trade": 0.0,
                         "error": "no equity"},
            )
        full = kelly_fraction(win_rate, avg_win, avg_loss)
        capped = cap_kelly(full, cap=cap)
        risk_per_trade = equity * capped
        suggested_volume = risk_per_trade / (equity * stop_distance)
        direction = "bullish" if capped > 0 else "neutral"
        return AIPrediction(
            module=self.name, symbol=ctx.symbol, direction=direction,
            confidence=min(1.0, capped * 4.0), horizon="short",
            payload={
                "kelly_fraction": round(full, 4),
                "capped_fraction": round(capped, 4),
                "suggested_volume": round(suggested_volume, 4),
                "risk_per_trade": round(risk_per_trade, 2),
                "cap_applied": cap,
                "win_rate": round(win_rate, 3),
                "payoff_ratio": round(avg_win / avg_loss, 3) if avg_loss > 0 else 0.0,
            },
        )
