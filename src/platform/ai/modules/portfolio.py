"""Cross-asset portfolio concentration analyzer AI module.

Aggregates open positions by broad asset category (fx, metals, crypto,
indices, commodities) and flags concentration risk whenever a single
category exceeds 40% of total notional exposure. Emits a diversification
score and concrete rebalance suggestions in the payload.
"""
from __future__ import annotations

from typing import Any

from platform.ai.orchestrator import AIContext, AIModule, AIPrediction

_FX_CCYS = ("USD", "EUR", "JPY", "GBP", "CHF", "AUD", "CAD", "NZD")
_CONCENTRATION_THRESHOLD = 0.40


def categorize(symbol: str) -> str:
    """Map a trading symbol to a broad asset category."""
    s = (symbol or "").upper()
    if "XAU" in s or "XAG" in s or "GOLD" in s or "SILVER" in s:
        return "metals"
    if any(x in s for x in ("BTC", "ETH", "XRP", "SOL", "DOGE", "ADA")):
        return "crypto"
    if any(x in s for x in ("SPX", "NDX", "DJI", "DAX", "UK100", "US30", "NAS100", "JP225")):
        return "indices"
    if any(x in s for x in ("OIL", "WTI", "BRENT", "NG", "CL", "XBR", "XTI")):
        return "commodities"
    # FX pairs contain two of the major currency codes
    ccys_in = [c for c in _FX_CCYS if c in s]
    if len(ccys_in) >= 2:
        return "fx"
    return "other"


def concentration(exposures: dict[str, float]) -> float:
    """Herfindahl-style concentration index in [0, 1].

    0 = perfectly diversified across many equal categories,
    1 = all exposure concentrated in a single category.
    """
    total = sum(exposures.values())
    if total <= 0:
        return 0.0
    shares = [v / total for v in exposures.values()]
    return sum(s * s for s in shares)


class PortfolioAI(AIModule):
    """Cross-asset portfolio concentration analyzer.

    Reads `positions` (list of {symbol, side, volume, pnl}) from
    ctx.features and computes per-category notional exposure. Any
    category exceeding the concentration threshold is flagged and a
    rebalance suggestion is emitted. Direction is always neutral; the
    confidence rises with concentration to flag the risk.
    """
    name = "portfolio"
    version = "1.0.0"

    async def analyze(self, ctx: AIContext) -> AIPrediction:
        positions = ctx.features.get("positions", []) or []
        exposures: dict[str, float] = {}
        for pos in positions:
            sym = pos.get("symbol", "")
            try:
                vol = abs(float(pos.get("volume", 0)))
            except (TypeError, ValueError):
                vol = 0.0
            cat = categorize(sym)
            exposures[cat] = exposures.get(cat, 0.0) + vol
        total = sum(exposures.values())
        conc = concentration(exposures)
        over_concentrated: list[str] = []
        suggestions: list[str] = []
        for cat, exp in exposures.items():
            share = exp / total if total > 0 else 0.0
            if share > _CONCENTRATION_THRESHOLD:
                over_concentrated.append(cat)
                suggestions.append(
                    f"Reduce {cat} exposure from {share:.0%} below {_CONCENTRATION_THRESHOLD:.0%}"
                )
        if not over_concentrated and total > 0:
            suggestions.append("Portfolio is well-diversified; no action needed")
        diversification = 1.0 - conc
        confidence = min(1.0, conc * 1.5) if over_concentrated else 0.3
        return AIPrediction(
            module=self.name, symbol=ctx.symbol, direction="neutral",
            confidence=confidence, horizon="medium",
            payload={
                "exposures": {k: round(v, 4) for k, v in exposures.items()},
                "concentration": round(conc, 3),
                "diversification_score": round(diversification, 3),
                "over_concentrated": over_concentrated,
                "suggested_rebalances": suggestions,
            },
        )
