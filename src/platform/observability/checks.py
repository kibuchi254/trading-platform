"""Concrete health checks for every platform subsystem.

Each check subclasses :class:`~platform.observability.health.HealthCheck`
and returns a :class:`~platform.observability.health.HealthStatus`. Checks
are intentionally small (30–50 lines), async, and defensive — a check
should *never* raise; failures must be reported as ``UNHEALTHY`` status
with the underlying exception captured in ``details``.

The checks here are the platform-default probes registered by
:func:`platform.observability.health.get_health_checker`. They cover:

* :class:`DatabaseHealthCheck` — asyncpg/SQLAlchemy ``SELECT 1``
* :class:`RedisHealthCheck` — pubsub backend ``PING``
* :class:`BridgeHealthCheck` — at least one MT5 terminal online
* :class:`CeleryHealthCheck` — at least one worker responsive
* :class:`RiskEngineHealthCheck` — kill-switch disengaged
* :class:`DiskSpaceHealthCheck` — Postgres data volume headroom
* :class:`MemoryHealthCheck` — host RAM pressure
"""

from __future__ import annotations

import time
from platform.core.config import get_settings
from platform.core.logging import get_logger
from platform.observability.health import HealthCheck, HealthState, HealthStatus
from typing import Any

_log = get_logger(__name__)


# ── Database ───────────────────────────────────────────────────────────


class DatabaseHealthCheck(HealthCheck):
    """Probe the async SQLAlchemy engine with ``SELECT 1``.

    Critical — the API cannot serve requests without a live database.
    """

    name = "database"
    critical = True

    async def check(self) -> HealthStatus:
        start = time.monotonic()
        try:
            from platform.db.session import db_context

            from sqlalchemy import text

            async with db_context() as session:
                result = await session.execute(text("SELECT 1"))
                value = result.scalar_one_or_none()
            latency_ms = (time.monotonic() - start) * 1000.0
            if value != 1:
                return HealthStatus(
                    name=self.name,
                    status=HealthState.UNHEALTHY,
                    latency_ms=latency_ms,
                    message=f"SELECT 1 returned {value!r}",
                    details={"scalar": value},
                )
            return HealthStatus(
                name=self.name,
                status=HealthState.HEALTHY,
                latency_ms=latency_ms,
                message="Database reachable",
            )
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000.0
            return HealthStatus(
                name=self.name,
                status=HealthState.UNHEALTHY,
                latency_ms=latency_ms,
                message=f"Database unreachable: {exc.__class__.__name__}",
                details={"error": str(exc)},
            )


# ── Redis ──────────────────────────────────────────────────────────────


class RedisHealthCheck(HealthCheck):
    """Probe the Redis backend with ``PING``.

    Critical — the event bus and Celery broker both depend on Redis.
    """

    name = "redis"
    critical = True

    async def check(self) -> HealthStatus:
        start = time.monotonic()
        try:
            import redis.asyncio as aioredis

            settings = get_settings()
            client = aioredis.from_url(settings.redis_url, decode_responses=True)
            try:
                pong = await client.ping()
            finally:
                await client.aclose()
            latency_ms = (time.monotonic() - start) * 1000.0
            status = HealthState.HEALTHY if pong else HealthState.UNHEALTHY
            return HealthStatus(
                name=self.name,
                status=status,
                latency_ms=latency_ms,
                message="Redis PING ok" if pong else "Redis PING returned False",
                details={"pong": pong},
            )
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000.0
            return HealthStatus(
                name=self.name,
                status=HealthState.UNHEALTHY,
                latency_ms=latency_ms,
                message=f"Redis unreachable: {exc.__class__.__name__}",
                details={"error": str(exc)},
            )


# ── MT5 Bridge ─────────────────────────────────────────────────────────


class BridgeHealthCheck(HealthCheck):
    """Probe the MT5 bridge — count terminals currently online.

    Critical — without at least one online terminal the platform cannot
    route orders. Reports ``DEGRADED`` if 0 terminals are online (the
    process is alive but trading is impossible) and ``UNHEALTHY`` only
    if the registry itself is unreachable.
    """

    name = "bridge"
    critical = True

    def __init__(self, min_terminals: int = 1) -> None:
        self.min_terminals = max(1, min_terminals)

    async def check(self) -> HealthStatus:
        start = time.monotonic()
        try:
            from platform.infrastructure.mt5_bridge.registry import get_registry

            registry = get_registry()
            terminals = await registry.list_online()
            latency_ms = (time.monotonic() - start) * 1000.0
            count = len(terminals)
            if count >= self.min_terminals:
                status = HealthState.HEALTHY
                message = f"{count} terminal(s) online"
            else:
                status = HealthState.DEGRADED
                message = f"Only {count} terminal(s) online (min {self.min_terminals})"
            return HealthStatus(
                name=self.name,
                status=status,
                latency_ms=latency_ms,
                message=message,
                details={"terminals_online": count, "min_required": self.min_terminals},
            )
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000.0
            return HealthStatus(
                name=self.name,
                status=HealthState.UNHEALTHY,
                latency_ms=latency_ms,
                message=f"Bridge registry error: {exc.__class__.__name__}",
                details={"error": str(exc)},
            )


# ── Celery ─────────────────────────────────────────────────────────────


class CeleryHealthCheck(HealthCheck):
    """Probe Celery by inspecting the active worker pool.

    Non-critical — the API can still serve traffic while Celery is down,
    but tick persistence, notifications, and backtests will pile up.
    Reports ``DEGRADED`` when no workers respond.
    """

    name = "celery"
    critical = False

    def __init__(self, timeout: float = 2.0) -> None:
        self.timeout = timeout

    async def check(self) -> HealthStatus:
        start = time.monotonic()
        try:
            from platform.infrastructure.celery_app import app

            inspect = app.control.inspect(timeout=self.timeout)
            # ``active`` is a synchronous RPC over the broker — run it in a
            # thread to avoid blocking the event loop.
            active = await _run_in_thread(inspect.active)
            latency_ms = (time.monotonic() - start) * 1000.0
            workers = list((active or {}).keys())
            if not workers:
                return HealthStatus(
                    name=self.name,
                    status=HealthState.DEGRADED,
                    latency_ms=latency_ms,
                    message="No Celery workers responding",
                    details={"workers": []},
                )
            return HealthStatus(
                name=self.name,
                status=HealthState.HEALTHY,
                latency_ms=latency_ms,
                message=f"{len(workers)} Celery worker(s) online",
                details={"workers": workers},
            )
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000.0
            return HealthStatus(
                name=self.name,
                status=HealthState.UNHEALTHY,
                latency_ms=latency_ms,
                message=f"Celery inspect failed: {exc.__class__.__name__}",
                details={"error": str(exc)},
            )


# ── Risk Engine ────────────────────────────────────────────────────────


class RiskEngineHealthCheck(HealthCheck):
    """Probe the risk engine — specifically the kill-switch state.

    Critical — a tripped kill-switch blocks every order; the platform is
    effectively read-only. Reports ``DEGRADED`` while engaged so on-call
    sees a clear signal without a hard-down alert.
    """

    name = "risk_engine"
    critical = True

    async def check(self) -> HealthStatus:
        start = time.monotonic()
        try:
            from platform.risk.engine import get_risk_engine

            engine = get_risk_engine()
            engaged = bool(getattr(engine.kill_switch, "_engaged", False))
            latency_ms = (time.monotonic() - start) * 1000.0
            rule_count = len(engine._rules)
            if engaged:
                return HealthStatus(
                    name=self.name,
                    status=HealthState.DEGRADED,
                    latency_ms=latency_ms,
                    message="Kill switch ENGAGED — all trading blocked",
                    details={"kill_switch": True, "rules": rule_count},
                )
            return HealthStatus(
                name=self.name,
                status=HealthState.HEALTHY,
                latency_ms=latency_ms,
                message="Risk engine nominal, kill switch disengaged",
                details={"kill_switch": False, "rules": rule_count},
            )
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000.0
            return HealthStatus(
                name=self.name,
                status=HealthState.UNHEALTHY,
                latency_ms=latency_ms,
                message=f"Risk engine error: {exc.__class__.__name__}",
                details={"error": str(exc)},
            )


# ── Disk Space ─────────────────────────────────────────────────────────


class DiskSpaceHealthCheck(HealthCheck):
    """Probe free space on the Postgres data volume.

    Non-critical until the disk fills up. Reports ``DEGRADED`` below 20 %
    free and ``UNHEALTHY`` below 5 %.
    """

    name = "disk_space"
    critical = False

    DEFAULT_PATH = "/var/lib/postgresql/data"
    WARN_PCT = 0.20  # <20 % free → DEGRADED
    CRIT_PCT = 0.05  # <5 % free → UNHEALTHY

    def __init__(
        self, path: str = DEFAULT_PATH, warn_pct: float = WARN_PCT, crit_pct: float = CRIT_PCT
    ) -> None:
        self.path = path
        self.warn_pct = warn_pct
        self.crit_pct = crit_pct

    async def check(self) -> HealthStatus:
        start = time.monotonic()
        try:
            import shutil

            usage = await _run_in_thread(lambda: shutil.disk_usage(self.path))
            latency_ms = (time.monotonic() - start) * 1000.0
            free_pct = usage.free / usage.total if usage.total else 0.0
            if free_pct < self.crit_pct:
                status = HealthState.UNHEALTHY
                message = f"Disk almost full: {free_pct:.1%} free on {self.path}"
            elif free_pct < self.warn_pct:
                status = HealthState.DEGRADED
                message = f"Disk low: {free_pct:.1%} free on {self.path}"
            else:
                status = HealthState.HEALTHY
                message = f"Disk ok: {free_pct:.1%} free on {self.path}"
            return HealthStatus(
                name=self.name,
                status=status,
                latency_ms=latency_ms,
                message=message,
                details={
                    "path": self.path,
                    "total_gb": round(usage.total / 1e9, 2),
                    "free_gb": round(usage.free / 1e9, 2),
                    "free_pct": round(free_pct, 4),
                },
            )
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000.0
            return HealthStatus(
                name=self.name,
                status=HealthState.UNHEALTHY,
                latency_ms=latency_ms,
                message=f"Disk probe failed: {exc.__class__.__name__}",
                details={"path": self.path, "error": str(exc)},
            )


# ── Memory ─────────────────────────────────────────────────────────────


class MemoryHealthCheck(HealthCheck):
    """Probe host memory pressure via :mod:`psutil`.

    Non-critical until the OOM killer wakes up. Reports ``DEGRADED`` above
    85 % usage and ``UNHEALTHY`` above 95 %.
    """

    name = "memory"
    critical = False

    WARN_PCT = 0.85
    CRIT_PCT = 0.95

    def __init__(self, warn_pct: float = WARN_PCT, crit_pct: float = CRIT_PCT) -> None:
        self.warn_pct = warn_pct
        self.crit_pct = crit_pct

    async def check(self) -> HealthStatus:
        start = time.monotonic()
        try:
            import psutil

            vm = await _run_in_thread(psutil.virtual_memory)
            latency_ms = (time.monotonic() - start) * 1000.0
            used_pct = vm.percent / 100.0
            if used_pct > self.crit_pct:
                status = HealthState.UNHEALTHY
                message = f"Memory critical: {used_pct:.1%} used"
            elif used_pct > self.warn_pct:
                status = HealthState.DEGRADED
                message = f"Memory pressure: {used_pct:.1%} used"
            else:
                status = HealthState.HEALTHY
                message = f"Memory ok: {used_pct:.1%} used"
            return HealthStatus(
                name=self.name,
                status=status,
                latency_ms=latency_ms,
                message=message,
                details={
                    "total_gb": round(vm.total / 1e9, 2),
                    "available_gb": round(vm.available / 1e9, 2),
                    "used_pct": round(used_pct, 4),
                },
            )
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000.0
            return HealthStatus(
                name=self.name,
                status=HealthState.UNHEALTHY,
                latency_ms=latency_ms,
                message=f"Memory probe failed: {exc.__class__.__name__}",
                details={"error": str(exc)},
            )


# ── Helpers ────────────────────────────────────────────────────────────


async def _run_in_thread(fn: Any) -> Any:
    """Run a blocking callable in the default executor and await it."""
    import asyncio
    import functools

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(fn))
