"""AI module SDK + orchestrator.

Each AI module is a specialized analyst: trend, pattern, risk, sentiment, etc.
The orchestrator fan-ins all module outputs and emits a single composite signal
(or a ranked list) that the strategy engine can consume.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class AIPrediction(BaseModel):
    module: str
    symbol: str | None = None
    direction: str = "neutral"  # bullish | bearish | neutral
    confidence: float = 0.0
    horizon: str = "short"  # short | medium | long
    payload: dict[str, Any] = {}


class AIContext(BaseModel):
    org_id: UUID
    symbol: str | None = None
    timeframe: str = "M15"
    features: dict[str, Any] = {}


class AIModule(abc.ABC):
    """Base class for all AI modules."""
    name: str = "abstract"
    version: str = "1.0.0"

    @abc.abstractmethod
    async def analyze(self, ctx: AIContext) -> AIPrediction:
        ...


class TrendAI(AIModule):
    """Local-first trend classifier using EMA slope + ADX thresholds.

    In production: load ONNX model trained offline. Here: simple heuristic
    that demonstrates the SDK shape.
    """
    name = "trend"
    version = "1.0.0"

    async def analyze(self, ctx: AIContext) -> AIPrediction:
        ema_fast = ctx.features.get("ema_fast", 0)
        ema_slow = ctx.features.get("ema_slow", 0)
        adx = ctx.features.get("adx", 0)

        if ema_fast > ema_slow and adx > 25:
            direction = "bullish"
            confidence = min(1.0, adx / 50)
        elif ema_fast < ema_slow and adx > 25:
            direction = "bearish"
            confidence = min(1.0, adx / 50)
        else:
            direction = "neutral"
            confidence = 0.3

        return AIPrediction(
            module=self.name, symbol=ctx.symbol, direction=direction,
            confidence=confidence, horizon="medium",
            payload={"ema_fast": ema_fast, "ema_slow": ema_slow, "adx": adx},
        )


class RiskAI(AIModule):
    """Evaluates market volatility regime + suggests position sizing."""
    name = "risk"
    version = "1.0.0"

    async def analyze(self, ctx: AIContext) -> AIPrediction:
        atr = ctx.features.get("atr", 0)
        atr_pct = ctx.features.get("atr_pct", 0)
        if atr_pct > 0.02:
            direction = "bearish"
            confidence = min(1.0, atr_pct * 20)
            payload = {"regime": "high_volatility", "suggested_size_factor": 0.5}
        else:
            direction = "neutral"
            confidence = 0.5
            payload = {"regime": "normal", "suggested_size_factor": 1.0}
        return AIPrediction(
            module=self.name, symbol=ctx.symbol, direction=direction,
            confidence=confidence, horizon="short", payload=payload,
        )


class LLMTradingAssistant(AIModule):
    """Conversational trading copilot powered by an LLM (OpenAI/Anthropic/vLLM).

    Used for natural-language queries: "Why did my EURUSD strategy underperform
    last week?" The LLM gets called with a context bundle (positions, recent
    trades, market regime) and returns plain text.
    """
    name = "llm_assistant"
    version = "1.0.0"

    async def analyze(self, ctx: AIContext) -> AIPrediction:
        # Real implementation calls self._call_llm(prompt) — see hybrid_ai.py
        return AIPrediction(
            module=self.name, symbol=ctx.symbol, direction="neutral",
            confidence=0.0, horizon="n/a",
            payload={"note": "LLM assistant returns free-form text, not predictions"},
        )


# ── Orchestrator ──────────────────────────────────────────────────────────


class AIOrchestrator:
    """Fan-in all AI module outputs into a composite signal."""

    def __init__(self) -> None:
        self._modules: dict[str, AIModule] = {}
        self.register(TrendAI())
        self.register(RiskAI())

    def register(self, module: AIModule) -> None:
        self._modules[module.name] = module

    async def analyze(self, ctx: AIContext) -> dict[str, AIPrediction]:
        results: dict[str, AIPrediction] = {}
        for name, module in self._modules.items():
            try:
                results[name] = await module.analyze(ctx)
            except Exception:  # noqa: BLE001
                # One failing module should not poison the orchestrator
                pass
        return results

    def composite_score(self, results: dict[str, AIPrediction]) -> float:
        """Weighted vote. Returns -1.0 (strong sell) to +1.0 (strong buy)."""
        score = 0.0
        total_weight = 0.0
        for name, p in results.items():
            w = self._weight(name, p.confidence)
            sign = {"bullish": 1, "bearish": -1, "neutral": 0}.get(p.direction, 0)
            score += sign * p.confidence * w
            total_weight += w
        return score / total_weight if total_weight else 0.0

    @staticmethod
    def _weight(name: str, confidence: float) -> float:
        # Per-module base weights — tune empirically
        base = {"trend": 1.0, "risk": 0.7, "pattern": 0.8, "sentiment": 0.5}.get(name, 0.5)
        return base * confidence


_orchestrator: AIOrchestrator | None = None


def get_ai_orchestrator() -> AIOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = AIOrchestrator()
    return _orchestrator
