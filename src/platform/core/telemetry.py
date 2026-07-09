"""OpenTelemetry + Prometheus wiring. Lightweight — meant to be extended per service."""

from __future__ import annotations

from platform.core.config import get_settings
from platform.core.logging import get_logger
from typing import Any

from prometheus_client import Counter, Gauge, Histogram, start_http_server

_log = get_logger(__name__)

# ── Metric registry ────────────────────────────────────────────────────────
HTTP_REQUESTS = Counter(
    "atlas_http_requests_total",
    "HTTP requests processed",
    ["method", "path", "status"],
)
HTTP_LATENCY = Histogram(
    "atlas_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
TERMINALS_ONLINE = Gauge("atlas_bridge_terminals_online", "MT5 terminals currently online")
BRIDGE_COMMANDS = Counter(
    "atlas_bridge_commands_total",
    "Commands dispatched to MT5 bridge",
    ["command", "terminal_id", "result"],
)
BRIDGE_COMMAND_LATENCY = Histogram(
    "atlas_bridge_command_duration_seconds",
    "Latency of bridge command round-trip",
    ["command"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
RISK_DECISIONS = Counter(
    "atlas_risk_decisions_total",
    "Risk engine decisions",
    ["decision"],  # approved | rejected | throttled
)
ORDERS_PLACED = Counter(
    "atlas_orders_placed_total", "Orders placed", ["terminal_id", "symbol", "side"]
)

# Worker / background-task metrics
TICKS_PERSISTED = Counter(
    "atlas_ticks_persisted_total",
    "Ticks persisted to the database (via Celery worker or TickStore)",
    ["source"],  # celery | tick_store
)
TASK_DURATION = Histogram(
    "atlas_celery_task_duration_seconds",
    "Celery task execution duration",
    ["task"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
)
TASK_RESULTS = Counter(
    "atlas_celery_task_results_total",
    "Celery task outcomes",
    ["task", "result"],  # result: success | failure | retry
)


def start_metrics_server() -> None:
    settings = get_settings()
    if settings.env == "test":
        return
    try:
        start_http_server(settings.prometheus_metrics_port)
        _log.info("metrics_server_started", port=settings.prometheus_metrics_port)
    except OSError as e:
        if e.errno in (98, 48, 10048):
            _log.info(
                "metrics_server_already_running",
                port=settings.prometheus_metrics_port,
                reason=str(e),
            )
        else:
            raise


def setup_tracing(app_name: str) -> Any:
    """Wire OpenTelemetry. Returns the tracer provider (or None if disabled)."""
    settings = get_settings()
    if not settings.otel_exporter_otlp_endpoint:
        return None
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:  # pragma: no cover
        _log.warning("otel_deps_missing")
        return None

    resource = Resource.create({"service.name": app_name, "deployment.environment": settings.env})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint))
    )
    trace.set_tracer_provider(provider)

    # NOTE: call FastAPIInstrumentor.instrument_app(app) from main.py after app creation
    return provider
