"""AI bounded context — AIPrediction + AIResult + CompositeSignal.

Models the prediction lifecycle: a value-object `AIPrediction` emitted by an
AI module, an `AIResult` aggregate that persists it and accepts feedback /
ground-truth labels for calibration, and `CompositeSignal` which fuses the
predictions of multiple modules into a single signed score.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID

from platform.core.exceptions import DomainError
from platform.domain.shared import AggregateRoot, DomainEvent, ValueObject


# ── Enums ───────────────────────────────────────────────────────────────────


class AIDirection(StrEnum):
    """Predicted direction of future price movement."""
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class AIHorizon(StrEnum):
    """Time horizon the prediction is meant to cover."""
    SHORT = "short"    # minutes → hours
    MEDIUM = "medium"  # hours → days
    LONG = "long"      # days → weeks


class AIFeedback(StrEnum):
    """Operator feedback on a recorded prediction."""
    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"
    NONE = "none"


class AICalibration(StrEnum):
    """Bucketed confidence level — used for routing & display."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ── Value objects ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AIConfidence(ValueObject):
    """Normalised confidence in [0.0, 1.0] with a derived calibration bucket."""
    value: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.value <= 1.0:
            raise DomainError(f"AIConfidence must be in [0,1], got {self.value}")

    @property
    def calibration_level(self) -> AICalibration:
        if self.value < 0.3:
            return AICalibration.LOW
        if self.value <= 0.7:
            return AICalibration.MEDIUM
        return AICalibration.HIGH

    def __float__(self) -> float:
        return self.value


@dataclass(frozen=True)
class AIPrediction(ValueObject):
    """An immutable AI module prediction.

    `input_hash` enables caching/dedup: two predictions with the same hash are
    the same prediction. `is_actionable` is the gate the executor checks before
    turning a prediction into a Signal.
    """
    module: str
    symbol: str
    direction: AIDirection
    confidence: AIConfidence
    horizon: AIHorizon = AIHorizon.SHORT
    payload: dict[str, Any] = field(default_factory=dict)
    model_version: str | None = None
    input_hash: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_actionable(self) -> bool:
        """True iff strong enough AND non-neutral — eligible to produce a signal."""
        return self.confidence.value > 0.5 and self.direction != AIDirection.NEUTRAL

    @property
    def signed_score(self) -> float:
        """Signed contribution in [-1, +1] — positive for bullish, negative for bearish."""
        sign = {
            AIDirection.BULLISH: 1.0,
            AIDirection.BEARISH: -1.0,
            AIDirection.NEUTRAL: 0.0,
        }[self.direction]
        return sign * self.confidence.value


@dataclass(frozen=True)
class CompositeSignal(ValueObject):
    """Fused output of multiple `AIPrediction`s for the same symbol.

    `score` is the mean of contributing predictions' `signed_score` and lives in
    [-1, +1]. `agreement_ratio` is the share of modules whose direction matches
    `dominant_direction` — a high ratio with a non-zero score is a consensus.
    """
    symbol: str
    score: float
    contributing_modules: dict[str, AIPrediction]
    dominant_direction: AIDirection
    agreement_ratio: float

    def __post_init__(self) -> None:
        if not -1.0 <= self.score <= 1.0:
            raise DomainError(f"CompositeSignal.score must be in [-1,1], got {self.score}")
        if not 0.0 <= self.agreement_ratio <= 1.0:
            raise DomainError(
                f"agreement_ratio must be in [0,1], got {self.agreement_ratio}"
            )

    @property
    def is_consensus(self) -> bool:
        """True iff >70% of modules agree on the dominant direction."""
        return self.agreement_ratio > 0.7


# ── Domain events ───────────────────────────────────────────────────────────


@dataclass(kw_only=True)
class AIPredictionRecorded(DomainEvent):
    ai_result_id: UUID
    org_id: UUID
    module: str
    symbol: str
    direction: str
    confidence: float


@dataclass(kw_only=True)
class AIFeedbackReceived(DomainEvent):
    ai_result_id: UUID
    feedback: str
    notes: str | None


@dataclass(kw_only=True)
class AIGroundTruthRecorded(DomainEvent):
    ai_result_id: UUID
    predicted: str
    actual: str
    correct: bool


# ── AIResult aggregate ──────────────────────────────────────────────────────


@dataclass(kw_only=True)
class AIResult(AggregateRoot):
    """Persisted AI prediction with feedback & ground-truth tracking.

    Lifecycle is implicit: created → optionally feedback_received → optionally
    ground_truth_recorded. All transitions are additive — once feedback is set
    it cannot be unset, only overridden by a new rating.
    """
    org_id: UUID
    module: str
    symbol: str
    timeframe: str | None
    prediction: AIPrediction
    confidence: AIConfidence
    model_version: str | None = None
    input_hash: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    feedback: AIFeedback = AIFeedback.NONE
    feedback_notes: str | None = None
    ground_truth: AIDirection | None = None
    ground_truth_recorded_at: datetime | None = None

    def __post_init__(self) -> None:
        self.record_event(
            AIPredictionRecorded(
                ai_result_id=self.id, org_id=self.org_id, module=self.module,
                symbol=self.symbol, direction=self.prediction.direction.value,
                confidence=self.confidence.value,
            )
        )

    def add_feedback(self, rating: AIFeedback, notes: str | None = None) -> None:
        """Record operator feedback on this prediction. Overwrites prior rating."""
        if rating == AIFeedback.NONE and notes:
            raise DomainError("Cannot attach notes to NONE feedback")
        self.feedback = rating
        self.feedback_notes = notes
        self.record_event(
            AIFeedbackReceived(
                ai_result_id=self.id, feedback=rating.value, notes=notes,
            )
        )

    def record_ground_truth(self, actual_direction: AIDirection) -> None:
        """Bind the realised direction — used for offline calibration studies.

        Idempotent guard: re-recording the same direction is a no-op; recording
        a different direction over an existing one is rejected.
        """
        if self.ground_truth is not None:
            if self.ground_truth == actual_direction:
                return
            raise DomainError(
                f"Ground truth already set to {self.ground_truth.value}"
            )
        self.ground_truth = actual_direction
        self.ground_truth_recorded_at = datetime.now(timezone.utc)
        correct = self.prediction.direction == actual_direction
        self.record_event(
            AIGroundTruthRecorded(
                ai_result_id=self.id,
                predicted=self.prediction.direction.value,
                actual=actual_direction.value,
                correct=correct,
            )
        )

    @property
    def was_correct(self) -> bool | None:
        """True iff ground truth was recorded and matches the prediction."""
        if self.ground_truth is None:
            return None
        return self.prediction.direction == self.ground_truth


__all__ = [
    "AIDirection", "AIHorizon", "AIFeedback", "AICalibration",
    "AIConfidence", "AIPrediction", "CompositeSignal",
    "AIPredictionRecorded", "AIFeedbackReceived", "AIGroundTruthRecorded",
    "AIResult",
]
