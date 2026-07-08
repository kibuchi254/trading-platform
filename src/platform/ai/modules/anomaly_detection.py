"""Tick-stream anomaly detector AI module (Isolation Forest-inspired).

Ingests a stream of tick samples and computes per-tick spreads, volumes,
and the inter-arrival tick rate. Outliers (|z| > 3) in spread or
volume, or a tick-rate spike, are flagged as anomalies. A bearish bias
is applied because microstructure anomalies often precede adverse
moves for the slower side of the book.
"""
from __future__ import annotations

import statistics
from typing import Any

from platform.ai.orchestrator import AIContext, AIModule, AIPrediction


def zscore(value: float, mean: float, std: float) -> float:
    """Return the z-score of `value` given `mean` and `std` (0 if degenerate)."""
    if std <= 0:
        return 0.0
    return (value - mean) / std


def detect_outliers(values: list[float], threshold: float = 3.0) -> list[int]:
    """Return indices of values whose |z-score| exceeds `threshold`."""
    if len(values) < 2:
        return []
    mean = statistics.fmean(values)
    std = statistics.pstdev(values)
    if std <= 0:
        return []
    return [i for i, v in enumerate(values) if abs(zscore(v, mean, std)) > threshold]


def _tick_rate(timestamps: list[float]) -> float:
    """Ticks per second across the sample window."""
    if len(timestamps) < 2:
        return 0.0
    span = timestamps[-1] - timestamps[0]
    if span <= 0:
        return 0.0
    return len(timestamps) / span


def _severity(count: int) -> str:
    if count >= 5:
        return "high"
    if count >= 2:
        return "medium"
    return "low"


class AnomalyDetectionAI(AIModule):
    """Tick-stream anomaly detector.

    Reads `tick_samples` (list of {bid, ask, volume, ts}) from
    ctx.features. Computes spread (ask − bid) and volume z-scores, flags
    outliers above 3σ, and detects tick-rate spikes. Direction is bearish
    when anomalies are present, neutral otherwise.
    """
    name = "anomaly_detection"
    version = "1.0.0"

    async def analyze(self, ctx: AIContext) -> AIPrediction:
        ticks = ctx.features.get("tick_samples", []) or []
        if len(ticks) < 5:
            return AIPrediction(
                module=self.name, symbol=ctx.symbol, direction="neutral",
                confidence=0.1, horizon="short",
                payload={"anomalies": [], "severity": "low"},
            )
        spreads = [float(t.get("ask", 0)) - float(t.get("bid", 0)) for t in ticks]
        volumes = [float(t.get("volume", 0)) for t in ticks]
        timestamps = [float(t.get("ts", 0)) for t in ticks]
        spread_mean = statistics.fmean(spreads)
        spread_std = statistics.pstdev(spreads) or 1e-9
        vol_mean = statistics.fmean(volumes)
        vol_std = statistics.pstdev(volumes) or 1e-9
        anomalies: list[dict[str, Any]] = []
        for i in detect_outliers(spreads, 3.0):
            anomalies.append({
                "index": i, "type": "spread_spike",
                "spread_z": round(zscore(spreads[i], spread_mean, spread_std), 2),
            })
        for i in detect_outliers(volumes, 3.0):
            anomalies.append({
                "index": i, "type": "volume_spike",
                "volume_z": round(zscore(volumes[i], vol_mean, vol_std), 2),
            })
        tick_rate = _tick_rate(timestamps)
        if tick_rate > 0 and len(timestamps) >= 10:
            half = timestamps[len(timestamps) // 2:]
            recent_rate = _tick_rate(half)
            if recent_rate > 2.0 * tick_rate:
                anomalies.append({"type": "tick_rate_spike",
                                  "rate": round(recent_rate, 2),
                                  "baseline": round(tick_rate, 2)})
        severity = _severity(len(anomalies))
        direction = "bearish" if anomalies else "neutral"
        confidence = min(1.0, len(anomalies) / 8.0)
        return AIPrediction(
            module=self.name, symbol=ctx.symbol, direction=direction,
            confidence=confidence, horizon="short",
            payload={
                "anomalies": anomalies,
                "severity": severity,
                "spread_mean": round(spread_mean, 6),
                "vol_mean": round(vol_mean, 4),
                "tick_rate": round(tick_rate, 2),
            },
        )
