"""Celery Beat schedule configuration for ATLAS.

Defines the periodic-task schedule consumed by ``celery -A platform.infrastructure.celery_app beat``.

Periodic jobs (UTC):
    ────────────────────────────────────────────────────────────────────
    Job                         Cadence        Queue         Notes
    ────────────────────────────────────────────────────────────────────
    flush_tick_buffer           every 30s      ticks         Fallback for TickStore
    sync_terminal_positions     every 5 min    default       (per-terminal) *
    cleanup_expired_signals     hourly         default       Marks stale signals
    reconcile_orders            hourly         default       (per-terminal) *
    archive_old_ticks           daily 02:00    default       Purge > 90d ticks
    ────────────────────────────────────────────────────────────────────
    * Per-terminal jobs are expanded by a separate scheduler (not Beat) —
      Beat enqueues a single fan-out task that lists all online terminals
      and dispatches one task per terminal. This keeps the beat schedule
      independent of DB state and avoids drift when terminals come and go.

Two helper tasks are registered here to perform that fan-out:

    * ``platform.tasks.fanout_sync_terminal_positions`` — lists all
      online terminals for every org and enqueues
      ``sync_terminal_positions`` for each.
    * ``platform.tasks.fanout_reconcile_orders`` — same pattern for
      ``reconcile_orders``.

Risk-threshold checks (``check_risk_thresholds``) are also fan-out:
``platform.tasks.fanout_check_risk_thresholds`` enqueues one
``check_risk_thresholds`` per org.
"""

from __future__ import annotations

from celery.schedules import crontab, schedule

# ── Beat schedule ────────────────────────────────────────────────────────────
# Each entry maps a logical name → ScheduleEntry dict. Celery reads this via
# ``app.conf.beat_schedule``.
beat_schedule: dict[str, dict] = {
    # ── Every 30 seconds ──────────────────────────────────────────────────
    "flush-tick-buffer-30s": {
        "task": "platform.tasks.flush_tick_buffer",
        "schedule": schedule(run_every=30.0),
        "options": {"queue": "ticks"},
    },
    # ── Every minute ──────────────────────────────────────────────────────
    "check-risk-thresholds-minute": {
        "task": "platform.tasks.fanout_check_risk_thresholds",
        "schedule": schedule(run_every=60.0),
        "options": {"queue": "default"},
    },
    # ── Every 5 minutes ───────────────────────────────────────────────────
    "sync-terminal-positions-5min": {
        "task": "platform.tasks.fanout_sync_terminal_positions",
        "schedule": schedule(run_every=300.0),
        "options": {"queue": "default"},
    },
    # ── Hourly (at minute 0) ──────────────────────────────────────────────
    "cleanup-expired-signals-hourly": {
        "task": "platform.tasks.cleanup_expired_signals",
        "schedule": crontab(minute=0),
        "options": {"queue": "default"},
    },
    "reconcile-orders-hourly": {
        "task": "platform.tasks.fanout_reconcile_orders",
        "schedule": crontab(minute=5),
        "options": {"queue": "default"},
    },
    "compute-performance-metrics-hourly": {
        "task": "platform.tasks.fanout_compute_performance_metrics",
        "schedule": crontab(minute=10),
        "options": {"queue": "default"},
    },
    # ── Daily at 02:00 UTC ────────────────────────────────────────────────
    "archive-old-ticks-daily": {
        "task": "platform.tasks.archive_old_ticks",
        "schedule": crontab(minute=0, hour=2),
        "kwargs": {"days": 90},
        "options": {"queue": "default"},
    },
    # ── Daily at 08:00 UTC — send daily reports to every active user ──────
    "send-daily-report-fanout": {
        "task": "platform.tasks.fanout_send_daily_report",
        "schedule": crontab(minute=0, hour=8),
        "options": {"queue": "notifications"},
    },
}


__all__ = ["beat_schedule"]
