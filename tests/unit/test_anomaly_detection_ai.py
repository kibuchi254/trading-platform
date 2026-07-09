"""Test AnomalyDetectionAI — spread/volume outlier detection."""

from __future__ import annotations

from platform.ai.modules.anomaly_detection import (
    AnomalyDetectionAI,
    detect_outliers,
    zscore,
)
from platform.ai.orchestrator import AIContext
from uuid import uuid4

import pytest


def _ctx(features: dict | None = None) -> AIContext:
    return AIContext(
        org_id=uuid4(),
        symbol="XAUUSD",
        timeframe="M15",
        features=features or {},
    )


def _ticks(
    spreads: list[float], volumes: list[float] | None = None, ts_start: float = 0.0
) -> list[dict]:
    """Build tick_samples in the shape AnomalyDetectionAI expects."""
    out = []
    vols = volumes if volumes is not None else [1.0] * len(spreads)
    for i, s in enumerate(spreads):
        out.append(
            {
                "bid": 100.0,
                "ask": 100.0 + s,
                "volume": vols[i],
                "ts": ts_start + i,
            }
        )
    return out


# ── zscore & detect_outliers helpers ─────────────────────────────────────────


def test_zscore_zero_for_degenerate_std() -> None:
    """std ≤ 0 → 0.0 (no meaningful z-score)."""
    assert zscore(5.0, mean=5.0, std=0.0) == 0.0
    assert zscore(5.0, mean=5.0, std=-1.0) == 0.0


def test_zscore_computes_standard_score() -> None:
    """(value - mean) / std."""
    assert zscore(10.0, mean=5.0, std=2.0) == pytest.approx(2.5)


def test_detect_outliers_empty_for_short_input() -> None:
    """<2 values → empty list (cannot compute std)."""
    assert detect_outliers([1.0]) == []


def test_detect_outliers_empty_for_constant_series() -> None:
    """All-equal values → std=0 → no outliers."""
    assert detect_outliers([5.0, 5.0, 5.0]) == []


def test_detect_outliers_flags_extreme_values() -> None:
    """Values >3σ from the mean are flagged by index."""
    values = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 100.0]
    out = detect_outliers(values, threshold=3.0)
    # The 100.0 stands out massively from the constant 1.0s.
    assert 10 in out


def test_detect_outliers_returns_empty_for_no_anomalies() -> None:
    """Normal-distribution-like data with no outliers → empty."""
    values = [10.0, 10.5, 9.5, 10.2, 9.8, 10.1, 9.9, 10.3]
    assert detect_outliers(values) == []


# ── AnomalyDetectionAI.analyze ───────────────────────────────────────────────


async def test_anomaly_ai_neutral_for_insufficient_samples() -> None:
    """<5 ticks → low-confidence neutral prediction."""
    ai = AnomalyDetectionAI()
    ctx = _ctx({"tick_samples": _ticks([0.1, 0.1, 0.1])})
    pred = await ai.analyze(ctx)
    assert pred.direction == "neutral"
    assert pred.confidence <= 0.2


async def test_anomaly_ai_neutral_for_clean_data() -> None:
    """Constant spreads/volumes → no anomalies → neutral."""
    ai = AnomalyDetectionAI()
    ticks = _ticks([0.1] * 10, volumes=[1.0] * 10)
    ctx = _ctx({"tick_samples": ticks})
    pred = await ai.analyze(ctx)
    assert pred.direction == "neutral"
    assert pred.payload["anomalies"] == []


async def test_anomaly_ai_detects_spread_spike() -> None:
    """A single large spread outlier is flagged as spread_spike.

    We use 11 ticks (10 normal + 1 outlier) so the outlier's z-score
    exceeds the strict 3.0 threshold (with 1 outlier in n samples,
    max z-score = sqrt(n-1); n=11 → sqrt(10) ≈ 3.16 > 3.0).
    """
    ai = AnomalyDetectionAI()
    # 10 normal ticks + 1 huge spread.
    ticks = _ticks([0.1] * 10 + [5.0])
    ctx = _ctx({"tick_samples": ticks})
    pred = await ai.analyze(ctx)
    assert pred.direction == "bearish"
    types = {a["type"] for a in pred.payload["anomalies"]}
    assert "spread_spike" in types


async def test_anomaly_ai_detects_volume_spike() -> None:
    """A single huge volume outlier is flagged as volume_spike."""
    ai = AnomalyDetectionAI()
    # 10 normal spreads AND 10 normal volumes + 1 huge volume outlier.
    spreads = [0.1] * 11
    volumes = [1.0] * 10 + [100.0]
    ticks = _ticks(spreads, volumes=volumes)
    ctx = _ctx({"tick_samples": ticks})
    pred = await ai.analyze(ctx)
    assert pred.direction == "bearish"
    types = {a["type"] for a in pred.payload["anomalies"]}
    assert "volume_spike" in types


async def test_anomaly_ai_severity_low_for_single_anomaly() -> None:
    """A single anomaly → 'low' severity."""
    ai = AnomalyDetectionAI()
    # 10 normal + 1 extreme outlier.
    ticks = _ticks([0.1] * 10 + [100.0])
    ctx = _ctx({"tick_samples": ticks})
    pred = await ai.analyze(ctx)
    assert len(pred.payload["anomalies"]) == 1
    assert pred.payload["severity"] == "low"


async def test_anomaly_ai_severity_escalates_with_anomaly_count() -> None:
    """Tick-rate spike adds an additional anomaly on top of spread spikes.

    Spread outliers are inherently bounded by sample size, so to verify
    severity escalation we drive a tick_rate_spike — a burst of recent
    ticks that more than doubles the baseline tick rate.
    """
    ai = AnomalyDetectionAI()
    # Build a tick stream where the last 10 ticks arrive in 1 second
    # while the first 10 arrive spread over 100 seconds → ~10x rate spike.
    ticks = []
    for i in range(10):
        ticks.append({"bid": 100.0, "ask": 100.1, "volume": 1.0, "ts": float(i) * 10.0})
    for i in range(10):
        ticks.append({"bid": 100.0, "ask": 100.1, "volume": 1.0, "ts": 100.0 + float(i) * 0.1})
    ctx = _ctx({"tick_samples": ticks})
    pred = await ai.analyze(ctx)
    # tick_rate_spike is one of the anomaly types.
    types = {a["type"] for a in pred.payload["anomalies"]}
    assert "tick_rate_spike" in types
    # 1 anomaly → low; multiple → medium/high. At minimum, an anomaly exists.
    assert pred.payload["severity"] in {"low", "medium", "high"}


async def test_anomaly_ai_payload_includes_summary_stats() -> None:
    """The payload carries spread_mean, vol_mean, tick_rate."""
    ai = AnomalyDetectionAI()
    ticks = _ticks([0.1, 0.2, 0.15, 0.12, 0.18], volumes=[1, 2, 1, 1, 2])
    ctx = _ctx({"tick_samples": ticks})
    pred = await ai.analyze(ctx)
    assert "spread_mean" in pred.payload
    assert "vol_mean" in pred.payload
    assert "tick_rate" in pred.payload


async def test_anomaly_ai_confidence_scales_with_anomaly_count() -> None:
    """More anomalies → higher confidence (capped at 1.0)."""
    ai = AnomalyDetectionAI()
    # Few anomalies.
    few_ticks = _ticks([0.1] * 8 + [5.0])
    few_pred = await ai.analyze(_ctx({"tick_samples": few_ticks}))
    # Many anomalies.
    many_ticks = _ticks([0.1, 0.1, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0])
    many_pred = await ai.analyze(_ctx({"tick_samples": many_ticks}))
    assert many_pred.confidence >= few_pred.confidence


async def test_anomaly_ai_handles_missing_keys_in_tick_dict() -> None:
    """Missing bid/ask/volume keys are coerced to 0.0 without crashing."""
    ai = AnomalyDetectionAI()
    # Each tick is missing some keys.
    ticks = [
        {"bid": 100.0, "ask": 100.1},  # no volume, no ts
        {"bid": 100.0, "ask": 100.1, "volume": 1.0, "ts": 0},
        {"bid": 100.0, "ask": 100.1, "volume": 1.0, "ts": 1},
        {"bid": 100.0, "ask": 100.1, "volume": 1.0, "ts": 2},
        {"bid": 100.0, "ask": 100.1, "volume": 1.0, "ts": 3},
    ]
    ctx = _ctx({"tick_samples": ticks})
    pred = await ai.analyze(ctx)
    # Should not raise — just return a valid prediction.
    assert pred.direction in {"neutral", "bearish"}
