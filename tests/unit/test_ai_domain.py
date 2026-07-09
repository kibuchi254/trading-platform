"""Test the AI domain — AIPrediction, AIConfidence, CompositeSignal, AIResult."""

from __future__ import annotations

from platform.core.exceptions import DomainError
from platform.domain.ai import (
    AICalibration,
    AIConfidence,
    AIDirection,
    AIFeedback,
    AIHorizon,
    AIPrediction,
    AIResult,
    CompositeSignal,
)
from uuid import uuid4

import pytest

# ── AIConfidence value object ────────────────────────────────────────────────


def test_ai_confidence_rejects_out_of_range() -> None:
    """Confidence must be in [0.0, 1.0]."""
    with pytest.raises(DomainError):
        AIConfidence(value=1.5)
    with pytest.raises(DomainError):
        AIConfidence(value=-0.01)


def test_ai_confidence_calibration_buckets() -> None:
    """<0.3=LOW, 0.3-0.7=MEDIUM, >0.7=HIGH."""
    assert AIConfidence(value=0.2).calibration_level == AICalibration.LOW
    assert AIConfidence(value=0.5).calibration_level == AICalibration.MEDIUM
    assert AIConfidence(value=0.71).calibration_level == AICalibration.HIGH


def test_ai_confidence_float_cast() -> None:
    """AIConfidence is usable as a float via __float__."""
    c = AIConfidence(value=0.42)
    assert float(c) == pytest.approx(0.42)


# ── AIPrediction value object ────────────────────────────────────────────────


def _make_pred(
    direction: AIDirection = AIDirection.BULLISH, confidence: float = 0.8
) -> AIPrediction:
    return AIPrediction(
        module="trend",
        symbol="XAUUSD",
        direction=direction,
        confidence=AIConfidence(value=confidence),
        horizon=AIHorizon.SHORT,
    )


def test_ai_prediction_is_actionable_only_when_strong_and_non_neutral() -> None:
    """Actionable requires confidence > 0.5 AND non-NEUTRAL direction."""
    assert _make_pred(AIDirection.BULLISH, 0.8).is_actionable
    assert not _make_pred(AIDirection.NEUTRAL, 0.8).is_actionable
    assert not _make_pred(AIDirection.BULLISH, 0.3).is_actionable


def test_ai_prediction_signed_score_matches_direction_and_confidence() -> None:
    """signed_score ∈ [-1, +1]: +conf for bullish, -conf for bearish, 0 neutral."""
    assert _make_pred(AIDirection.BULLISH, 0.7).signed_score == pytest.approx(0.7)
    assert _make_pred(AIDirection.BEARISH, 0.6).signed_score == pytest.approx(-0.6)
    assert _make_pred(AIDirection.NEUTRAL, 0.9).signed_score == pytest.approx(0.0)


# ── CompositeSignal value object ─────────────────────────────────────────────


def test_composite_signal_rejects_score_out_of_range() -> None:
    """Composite score must lie in [-1, +1]."""
    pred = _make_pred()
    with pytest.raises(DomainError):
        CompositeSignal(
            symbol="XAUUSD",
            score=1.5,
            contributing_modules={"trend": pred},
            dominant_direction=AIDirection.BULLISH,
            agreement_ratio=0.8,
        )


def test_composite_signal_rejects_bad_agreement_ratio() -> None:
    """agreement_ratio must lie in [0, 1]."""
    pred = _make_pred()
    with pytest.raises(DomainError):
        CompositeSignal(
            symbol="XAUUSD",
            score=0.5,
            contributing_modules={"trend": pred},
            dominant_direction=AIDirection.BULLISH,
            agreement_ratio=1.5,
        )


def test_composite_signal_is_consensus_when_agreement_above_seventy_pct() -> None:
    """A 71% agreement ratio crosses the consensus threshold."""
    pred = _make_pred()
    sig = CompositeSignal(
        symbol="XAUUSD",
        score=0.6,
        contributing_modules={"trend": pred},
        dominant_direction=AIDirection.BULLISH,
        agreement_ratio=0.71,
    )
    assert sig.is_consensus


def test_composite_signal_not_consensus_at_low_agreement() -> None:
    """Below 70% agreement is not a consensus."""
    pred = _make_pred()
    sig = CompositeSignal(
        symbol="XAUUSD",
        score=0.4,
        contributing_modules={"trend": pred},
        dominant_direction=AIDirection.BULLISH,
        agreement_ratio=0.5,
    )
    assert not sig.is_consensus


# ── AIResult aggregate ───────────────────────────────────────────────────────


def _make_result(direction: AIDirection = AIDirection.BULLISH) -> AIResult:
    return AIResult(
        org_id=uuid4(),
        module="trend",
        symbol="XAUUSD",
        timeframe="M15",
        prediction=_make_pred(direction, 0.8),
        confidence=AIConfidence(value=0.8),
        model_version="1.0.0",
    )


def test_ai_result_starts_with_no_feedback_no_ground_truth() -> None:
    """Fresh AIResult has NONE feedback and no ground truth."""
    r = _make_result()
    assert r.feedback == AIFeedback.NONE
    assert r.ground_truth is None
    assert r.was_correct is None


def test_ai_result_records_emitted_event_on_creation() -> None:
    """Construction emits AIPredictionRecorded."""
    r = _make_result()
    events = r.collect_events()
    assert len(events) == 1
    assert events[0].__class__.__name__ == "AIPredictionRecorded"


def test_ai_result_add_feedback_overwrites_previous() -> None:
    """Repeated feedback calls overwrite (no lifecycle guard)."""
    r = _make_result()
    r.add_feedback(AIFeedback.THUMBS_UP)
    assert r.feedback == AIFeedback.THUMBS_UP
    r.add_feedback(AIFeedback.THUMBS_DOWN, notes="bad call")
    assert r.feedback == AIFeedback.THUMBS_DOWN
    assert r.feedback_notes == "bad call"


def test_ai_result_add_feedback_rejects_notes_with_none_rating() -> None:
    """Notes cannot be attached to a NONE feedback."""
    r = _make_result()
    with pytest.raises(DomainError):
        r.add_feedback(AIFeedback.NONE, notes="should not be allowed")


def test_ai_result_record_ground_truth_first_time_sets_correct() -> None:
    """Recording ground truth matching prediction marks was_correct=True."""
    r = _make_result(AIDirection.BULLISH)
    r.record_ground_truth(AIDirection.BULLISH)
    assert r.ground_truth == AIDirection.BULLISH
    assert r.was_correct is True
    assert r.ground_truth_recorded_at is not None


def test_ai_result_record_ground_truth_mismatch_marks_incorrect() -> None:
    """Recording a different ground truth marks was_correct=False."""
    r = _make_result(AIDirection.BULLISH)
    r.record_ground_truth(AIDirection.BEARISH)
    assert r.was_correct is False


def test_ai_result_record_ground_truth_idempotent_same_value() -> None:
    """Re-recording the same direction is a no-op."""
    r = _make_result(AIDirection.BULLISH)
    r.record_ground_truth(AIDirection.BULLISH)
    # Second call with same direction should NOT raise.
    r.record_ground_truth(AIDirection.BULLISH)
    assert r.ground_truth == AIDirection.BULLISH


def test_ai_result_record_ground_truth_rejects_conflicting_value() -> None:
    """Recording a different direction over an existing one raises."""
    r = _make_result(AIDirection.BULLISH)
    r.record_ground_truth(AIDirection.BULLISH)
    with pytest.raises(DomainError):
        r.record_ground_truth(AIDirection.BEARISH)


def test_ai_result_record_ground_truth_emits_event_with_correct_flag() -> None:
    """AIGroundTruthRecorded carries whether the prediction was correct."""
    r = _make_result(AIDirection.BULLISH)
    r.collect_events()  # drain AIPredictionRecorded
    r.record_ground_truth(AIDirection.BULLISH)
    events = r.collect_events()
    assert len(events) == 1
    assert events[0].__class__.__name__ == "AIGroundTruthRecorded"
    assert events[0].correct is True
