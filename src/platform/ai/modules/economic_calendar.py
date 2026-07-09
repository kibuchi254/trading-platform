"""Economic calendar event surprise analyzer AI module.

Scans the upcoming/recent economic calendar for high-impact macro
releases (NFP, CPI, FOMC, ECB, …) and computes each event's surprise
(actual − forecast, normalized by the previous reading). Aggregated
surprise drives direction on USD-paired symbols; output horizon is
medium because macro surprises persist for hours to days.
"""

from __future__ import annotations

from platform.ai.orchestrator import AIContext, AIModule, AIPrediction
from typing import Any

_HIGH_IMPACT_EVENTS = {
    "NFP",
    "Nonfarm Payrolls",
    "Non-Farm Payrolls",
    "CPI",
    "Core CPI",
    "FOMC",
    "ECB",
    "Fed Rate Decision",
    "GDP",
    "PCE",
    "Core PCE",
    "ISM",
    "PMI",
}


def event_surprise(actual: float | None, forecast: float | None) -> float:
    """Return actual - forecast; missing values yield 0."""
    if actual is None or forecast is None:
        return 0.0
    try:
        return float(actual) - float(forecast)
    except (TypeError, ValueError):
        return 0.0


def impact_weight(impact: str) -> float:
    """Map an event impact label to a weight in [0, 1]."""
    s = (impact or "").lower()
    if s in ("high", "critical"):
        return 1.0
    if s in ("medium", "moderate"):
        return 0.6
    if s in ("low", "minor"):
        return 0.3
    return 0.5


def _is_high_impact(event: dict[str, Any]) -> bool:
    name = str(event.get("name", event.get("event", "")))
    if name in _HIGH_IMPACT_EVENTS:
        return True
    return event.get("impact", "").lower() in ("high", "critical")


def _symbol_uses_usd(symbol: str) -> bool:
    return "USD" in (symbol or "").upper() or symbol.upper() in {"DXY", "USDX", "DX"}


class EconomicCalendarAI(AIModule):
    """Economic calendar surprise analyzer.

    Reads `events` (list of {ts, impact, currency, forecast, previous,
    actual, name}) from ctx.features. For each high-impact release the
    surprise is normalized by the prior reading and weighted by the
    event's impact. A positive USD surprise is bullish for USD-paired
    symbols (per spec: better economy → stronger currency).
    """

    name = "economic_calendar"
    version = "1.0.0"

    async def analyze(self, ctx: AIContext) -> AIPrediction:
        events = ctx.features.get("events", []) or []
        if not events:
            return AIPrediction(
                module=self.name,
                symbol=ctx.symbol,
                direction="neutral",
                confidence=0.1,
                horizon="medium",
                payload={"event_count": 0, "high_impact": 0},
            )
        is_usd = _symbol_uses_usd(ctx.symbol or "")
        weighted = 0.0
        weight_total = 0.0
        high_impact_count = 0
        for ev in events:
            if not _is_high_impact(ev):
                continue
            high_impact_count += 1
            w = impact_weight(ev.get("impact", "medium"))
            surprise = event_surprise(ev.get("actual"), ev.get("forecast"))
            prev = ev.get("previous")
            try:
                denom = abs(float(prev)) if prev is not None else 1.0
            except (TypeError, ValueError):
                denom = 1.0
            denom = max(denom, 1e-9)
            norm = surprise / denom
            currency = (ev.get("currency") or "").upper()
            if currency == "USD" and is_usd:
                sign = 1.0
            elif currency == "USD":
                sign = -1.0
            else:
                sign = 0.5
            weighted += norm * w * sign
            weight_total += w
        if weight_total == 0:
            return AIPrediction(
                module=self.name,
                symbol=ctx.symbol,
                direction="neutral",
                confidence=0.2,
                horizon="medium",
                payload={"event_count": len(events), "high_impact": 0},
            )
        net = weighted / weight_total
        direction = "bullish" if net > 0.1 else "bearish" if net < -0.1 else "neutral"
        confidence = min(1.0, abs(net))
        return AIPrediction(
            module=self.name,
            symbol=ctx.symbol,
            direction=direction,
            confidence=confidence,
            horizon="medium",
            payload={
                "event_count": len(events),
                "high_impact": high_impact_count,
                "weighted_surprise": round(net, 4),
            },
        )
