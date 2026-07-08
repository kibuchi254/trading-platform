"""AIResultRepository — persistence for the AIResult aggregate.

Converts between the SQLAlchemy `AIResult` row and the domain `AIResult`
aggregate. The aggregate owns its feedback / ground-truth lifecycle; the
repository exposes a thin `add_feedback` shortcut used by the feedback API
endpoint (the canonical path is `aggregate.add_feedback(...)` then `save`).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from platform.db.models import AIResult as AIResultModel
from platform.domain.ai import (
    AIConfidence, AIDirection, AIFeedback, AIPrediction, AIResult,
)


class AIResultRepository:
    """Async repository for the AIResult aggregate."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Conversions ─────────────────────────────────────────────────────────

    @staticmethod
    def to_domain(m: AIResultModel) -> AIResult:
        prediction_payload = m.prediction or {}
        direction = AIDirection(prediction_payload.get("direction", "neutral"))
        confidence = AIConfidence(value=float(m.confidence))
        result = AIResult(
            id=m.id,
            org_id=m.org_id,
            module=m.module,
            symbol=m.symbol or "",
            timeframe=m.timeframe,
            prediction=AIPrediction(
                module=m.module, symbol=m.symbol or "",
                direction=direction, confidence=confidence,
                payload=prediction_payload,
                model_version=m.model_version, input_hash=m.input_hash,
                created_at=m.created_at,
            ),
            confidence=confidence,
            model_version=m.model_version,
            input_hash=m.input_hash,
            created_at=m.created_at,
        )
        # Side-channel feedback fields for round-trip via save().
        result.feedback = AIFeedback(prediction_payload.get("feedback", "none"))  # type: ignore[assignment]
        result.feedback_notes = prediction_payload.get("feedback_notes")  # type: ignore[assignment]
        return result

    @staticmethod
    def from_domain(e: AIResult) -> AIResultModel:
        prediction_payload: dict = dict(e.prediction.payload)
        prediction_payload["direction"] = e.prediction.direction.value
        prediction_payload["feedback"] = e.feedback.value
        prediction_payload["feedback_notes"] = e.feedback_notes
        return AIResultModel(
            id=e.id,
            org_id=e.org_id,
            module=e.module,
            symbol=e.symbol or None,
            timeframe=e.timeframe,
            prediction=prediction_payload,
            confidence=e.confidence.value,
            model_version=e.model_version,
            input_hash=e.input_hash,
        )

    # ── Reads ───────────────────────────────────────────────────────────────

    async def get(self, id: UUID) -> AIResult | None:
        m = await self.db.get(AIResultModel, id)
        return self.to_domain(m) if m else None

    async def list_by_module(
        self, org_id: UUID, module: str, *, limit: int = 100,
    ) -> list[AIResult]:
        stmt = (
            select(AIResultModel)
            .where(AIResultModel.org_id == org_id, AIResultModel.module == module)
            .order_by(AIResultModel.created_at.desc())
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [self.to_domain(r) for r in rows]

    async def list_by_symbol(
        self, org_id: UUID, symbol: str, *, limit: int = 100,
    ) -> list[AIResult]:
        stmt = (
            select(AIResultModel)
            .where(AIResultModel.org_id == org_id, AIResultModel.symbol == symbol)
            .order_by(AIResultModel.created_at.desc())
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [self.to_domain(r) for r in rows]

    async def list_recent_by_org(
        self, org_id: UUID, *, since: datetime | None = None, limit: int = 100,
    ) -> list[AIResult]:
        cutoff = since or (datetime.now(timezone.utc) - timedelta(hours=24))
        stmt = (
            select(AIResultModel)
            .where(AIResultModel.org_id == org_id, AIResultModel.created_at >= cutoff)
            .order_by(AIResultModel.created_at.desc())
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [self.to_domain(r) for r in rows]

    # ── Writes ──────────────────────────────────────────────────────────────

    async def add(self, entity: AIResult) -> AIResult:
        self.db.add(self.from_domain(entity))
        await self.db.flush()
        return entity

    async def add_feedback(
        self, id: UUID, rating: str, notes: str | None = None,
    ) -> bool:
        """Persist operator feedback into the prediction JSONB blob."""
        rating_enum = AIFeedback(rating)
        if rating_enum == AIFeedback.NONE and notes:
            from platform.core.exceptions import DomainError
            raise DomainError("Cannot attach notes to NONE feedback")
        # Merge feedback into the JSONB prediction column via key->'feedback'.
        m = await self.db.get(AIResultModel, id)
        if m is None:
            return False
        payload = dict(m.prediction or {})
        payload["feedback"] = rating_enum.value
        payload["feedback_notes"] = notes
        m.prediction = payload
        await self.db.flush()
        return True
