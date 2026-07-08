"""Run the AI orchestrator and return composite + per-module predictions.

Vertical slice:

  API → query → AIContext(org_id, symbol, timeframe, features)
        → AIOrchestrator.analyze(ctx) → dict[module_name → AIPrediction]
        → composite_score(results) → float in [-1.0, +1.0]
        → persist AIResult rows for each module (best-effort)
        → return composite + per-module DTOs

The orchestrator runs every registered module (trend, risk, ...) and folds
their outputs into a single composite score. The query is read-side only —
it does not place trades; the strategy engine subscribes to ``AI_RESULTS``
events and decides whether to act on the composite.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from platform.ai.orchestrator import (
    AIContext,
    AIOrchestrator,
    AIPrediction,
    get_ai_orchestrator,
)
from platform.core.logging import get_logger
from platform.db.models import AIResult
from platform.db.session import db_context
from platform.events.bus import get_event_bus
from platform.events.topics import Topic

_log = get_logger(__name__)


# ── Query + DTO ────────────────────────────────────────────────────────────


class GetAIAnalysisQuery(BaseModel):
    org_id: UUID
    symbol: str
    timeframe: str = "M15"
    features: dict[str, Any] = {}


class ModulePrediction(BaseModel):
    module: str
    symbol: str | None
    direction: str
    confidence: float
    horizon: str
    payload: dict[str, Any]


class GetAIAnalysisResult(BaseModel):
    org_id: UUID
    symbol: str
    timeframe: str
    composite_score: float  # -1.0 (strong sell) .. +1.0 (strong buy)
    composite_direction: str  # bullish | bearish | neutral
    modules: list[ModulePrediction]
    computed_at: str


# ── Handler ─────────────────────────────────────────────────────────────────


async def handle_get_ai_analysis(query: GetAIAnalysisQuery) -> GetAIAnalysisResult:
    """Run every AI module, fold into a composite, persist + emit + return."""
    orchestrator: AIOrchestrator = get_ai_orchestrator()
    ctx = AIContext(
        org_id=query.org_id,
        symbol=query.symbol,
        timeframe=query.timeframe,
        features=query.features,
    )

    results: dict[str, AIPrediction] = await orchestrator.analyze(ctx)
    composite = orchestrator.composite_score(results)
    composite_direction = (
        "bullish" if composite > 0.15
        else "bearish" if composite < -0.15
        else "neutral"
    )
    now = datetime.now(timezone.utc)

    # Persist each module's prediction as an AIResult row (best-effort — a
    # failure here must not mask the analysis returned to the caller).
    try:
        async with db_context() as db:
            for name, pred in results.items():
                db.add(
                    AIResult(
                        org_id=query.org_id,
                        module=name,
                        symbol=query.symbol,
                        timeframe=query.timeframe,
                        prediction={
                            "direction": pred.direction,
                            "confidence": pred.confidence,
                            "horizon": pred.horizon,
                            "payload": pred.payload,
                            "composite_score": composite,
                        },
                        confidence=pred.confidence,
                        model_version=getattr(
                            orchestrator._modules.get(name), "version", "1.0.0"
                        ),
                    )
                )
            await db.commit()
    except Exception:  # noqa: BLE001
        _log.exception("ai_result_persist_failed", org_id=str(query.org_id))

    await get_event_bus().publish(
        Topic.AI_RESULTS,
        {
            "type": "ai_analysis",
            "org_id": str(query.org_id),
            "symbol": query.symbol,
            "timeframe": query.timeframe,
            "composite_score": composite,
            "composite_direction": composite_direction,
            "modules": {
                name: p.model_dump() for name, p in results.items()
            },
            "computed_at": now.isoformat(),
        },
    )

    return GetAIAnalysisResult(
        org_id=query.org_id,
        symbol=query.symbol,
        timeframe=query.timeframe,
        composite_score=round(composite, 4),
        composite_direction=composite_direction,
        modules=[
            ModulePrediction(
                module=p.module,
                symbol=p.symbol,
                direction=p.direction,
                confidence=round(p.confidence, 4),
                horizon=p.horizon,
                payload=dict(p.payload or {}),
            )
            for p in results.values()
        ],
        computed_at=now.isoformat(),
    )
