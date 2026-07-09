"""News + social sentiment analyzer AI module.

Tokenizes each headline supplied in the context and scores tokens against
curated bullish/bearish word lists. The aggregated net sentiment drives
the direction (bullish/bearish/neutral) and the confidence scales with
the magnitude of the net score.
"""

from __future__ import annotations

import re
from collections import Counter
from platform.ai.orchestrator import AIContext, AIModule, AIPrediction

_POSITIVE: dict[str, float] = {
    "rally": 1.0,
    "surge": 1.0,
    "breakthrough": 1.2,
    "beat": 0.8,
    "soar": 1.0,
    "gain": 0.6,
    "growth": 0.6,
    "upgrade": 0.7,
    "bullish": 1.0,
    "outperform": 0.8,
    "buy": 0.7,
    "strong": 0.5,
    "record": 0.7,
    "high": 0.4,
    "recovery": 0.7,
    "optimism": 0.7,
    "profit": 0.7,
    "dividend": 0.5,
    "deal": 0.5,
}
_NEGATIVE: dict[str, float] = {
    "crash": -1.2,
    "plunge": -1.0,
    "miss": -0.8,
    "warning": -0.7,
    "drop": -0.6,
    "fall": -0.6,
    "bearish": -1.0,
    "downgrade": -0.8,
    "sell": -0.7,
    "loss": -0.6,
    "weak": -0.5,
    "low": -0.4,
    "recession": -1.0,
    "fear": -0.7,
    "panic": -1.0,
    "collapse": -1.2,
    "fraud": -1.0,
    "lawsuit": -0.7,
    "default": -1.0,
}
_TOKEN_RE = re.compile(r"[a-zA-Z]+")
_THRESHOLD = 0.15


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def score_text(text: str) -> float:
    """Score a single text string into the range [-1.0, +1.0]."""
    tokens = _tokenize(text)
    if not tokens:
        return 0.0
    counts = Counter(tokens)
    score = 0.0
    total = 0
    for word, weight in _POSITIVE.items():
        if word in counts:
            score += weight * counts[word]
            total += counts[word]
    for word, weight in _NEGATIVE.items():
        if word in counts:
            score += weight * counts[word]
            total += counts[word]
    if total == 0:
        return 0.0
    norm = score / total
    return max(-1.0, min(1.0, norm))


class SentimentAI(AIModule):
    """News + social sentiment analyzer.

    Reads `headlines` (list[str]) from ctx.features and produces a net
    sentiment score per headline. Direction flips bullish above +0.15 and
    bearish below -0.15; confidence grows linearly with the magnitude of
    the net sentiment (capped at 1.0).
    """

    name = "sentiment"
    version = "1.0.0"

    async def analyze(self, ctx: AIContext) -> AIPrediction:
        headlines = ctx.features.get("headlines", []) or []
        if not headlines:
            return AIPrediction(
                module=self.name,
                symbol=ctx.symbol,
                direction="neutral",
                confidence=0.1,
                horizon="medium",
                payload={"net_sentiment": 0.0, "headline_count": 0},
            )
        scores = [score_text(h) for h in headlines]
        net = sum(scores) / len(scores)
        if net > _THRESHOLD:
            direction = "bullish"
        elif net < -_THRESHOLD:
            direction = "bearish"
        else:
            direction = "neutral"
        confidence = min(1.0, abs(net) * 2.0)
        return AIPrediction(
            module=self.name,
            symbol=ctx.symbol,
            direction=direction,
            confidence=confidence,
            horizon="medium",
            payload={
                "net_sentiment": round(net, 3),
                "headline_count": len(headlines),
                "max_score": round(max(scores), 3),
                "min_score": round(min(scores), 3),
            },
        )
