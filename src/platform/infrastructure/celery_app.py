"""Celery app — background workers for heavy / async tasks.

The app is constructed here with broker / backend / serializer config and
the task routing table. The *implementations* live in
:mod:`platform.infrastructure.tasks` and are imported at the bottom of
this module so Celery's autodiscovery picks them up when the worker
starts.

Celery Beat's periodic schedule is defined in
:mod:`platform.infrastructure.celery_schedules` and wired into
``app.conf.beat_schedule`` below — start the scheduler with::

    celery -A platform.infrastructure.celery_app beat

Tasks subscribe to events via Redis pubsub or get enqueued by handlers.
"""

from __future__ import annotations

from platform.core.config import get_settings
from platform.infrastructure.celery_schedules import beat_schedule
from typing import Any

from celery import Celery
from celery.signals import worker_ready

settings = get_settings()

app = Celery("atlas", broker=settings.celery_broker_url, backend=settings.celery_result_backend)
app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # ── Task routing ────────────────────────────────────────────────────
    # Hot paths get dedicated queues so a back-log in one category cannot
    # starve another. Workers bind to one or more queues via ``-Q``.
    task_routes={
        "platform.tasks.persist_tick": {"queue": "ticks"},
        "platform.tasks.persist_execution": {"queue": "trades"},
        "platform.tasks.persist_position_update": {"queue": "trades"},
        "platform.tasks.persist_account_update": {"queue": "trades"},
        "platform.tasks.run_backtest": {"queue": "backtest"},
        "platform.tasks.send_notification": {"queue": "notifications"},
        "platform.tasks.send_daily_report": {"queue": "notifications"},
        "platform.tasks.sync_terminal_positions": {"queue": "default"},
        "platform.tasks.sync_terminal_account": {"queue": "default"},
        "platform.tasks.cleanup_expired_signals": {"queue": "default"},
        "platform.tasks.archive_old_ticks": {"queue": "default"},
        "platform.tasks.compute_performance_metrics": {"queue": "default"},
        "platform.tasks.check_risk_thresholds": {"queue": "default"},
        "platform.tasks.reconcile_orders": {"queue": "default"},
        "platform.tasks.flush_tick_buffer": {"queue": "ticks"},
    },
    # ── Beat schedule ───────────────────────────────────────────────────
    # Periodic jobs (sync_terminal_positions every 5m, archive_old_ticks
    # daily at 02:00, check_risk_thresholds every minute, etc.). See
    # :mod:`platform.infrastructure.celery_schedules` for the full table.
    beat_schedule=beat_schedule,
    # ── Reliability ─────────────────────────────────────────────────────
    # Visibility timeout — must exceed the longest task.
    broker_visibility_timeout=3600,
    result_expires=3600,
)


@worker_ready.connect
def _on_ready(sender: Any, **_kwargs: Any) -> None:
    from platform.core.logging import configure_logging, get_logger

    configure_logging()
    get_logger(__name__).info("celery_worker_ready", host=sender.hostname)


# ── Task registration ────────────────────────────────────────────────────────
#
# Importing :mod:`platform.infrastructure.tasks` registers every ``@app.task``
# decorator with the Celery app. We import at the bottom (not the top) to
# avoid a circular import: ``tasks`` imports ``app`` from this module.
#
# The import is wrapped in a try/except so that environments without the
# full optional dependency stack (e.g. a stripped-down Celery-only
# container) can still load the app for introspection purposes.
try:
    from platform.infrastructure import tasks as _tasks  # noqa: F401
except Exception:
    import logging

    logging.getLogger(__name__).exception("celery_tasks_import_failed")
