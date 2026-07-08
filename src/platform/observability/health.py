"""Health checks — fine-grained probes for every critical subsystem.

A :class:`HealthCheck` is a small async callable that knows how to verify a
single dependency (database, redis, bridge, celery, risk engine, etc.).
Each check returns a :class:`HealthStatus` describing whether the dependency
is ``HEALTHY`` / ``DEGRADED`` / ``UNHEALTHY`` plus a latency measurement and
free-form details payload for the operator.

The :class:`HealthChecker` aggregates checks, runs them concurrently, and
computes an overall system status used by the ``/health/live`` and
``/health/ready`` endpoints. Checks can be marked ``critical=True`` — a
failing critical check forces the overall verdict to ``UNHEALTHY``, which
in turn drives Kubernetes pod-eviction and load-balancer drain behaviour.

Design notes
------------
* All checks are async so the orchestrator can fan them out concurrently
  with :func:`asyncio.gather` — a slow database ping will not stall the
  redis check.
* Latency is measured with :func:`time.monotonic` to avoid wall-clock
  jumps during NTP syncs.
* Failures inside a check are caught and converted to ``UNHEALTHY``
  rather than propagating — one bad check must never crash the probe.
"""
from __future__ import annotations

import abc
import asyncio
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from platform.core.logging import get_logger

_log = get_logger(__name__)


class HealthState(str, Enum):
    """Three-state health enum used by every :class:`HealthStatus`."""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"


class HealthStatus(BaseModel):
    """Result of a single health check.

    Attributes
    ----------
    name:
        Identifier of the check (matches :attr:`HealthCheck.name`).
    status:
        Coarse-grained state — see :class:`HealthState`.
    latency_ms:
        Wall-clock duration of the probe in milliseconds.
    message:
        Human-readable summary, safe to surface in a UI.
    details:
        Arbitrary structured payload (counts, error stack, etc.).
    ts:
        UTC timestamp at which the check was executed.
    """

    name: str
    status: HealthState
    latency_ms: float = 0.0
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class HealthCheck(abc.ABC):
    """Abstract base class for every health check.

    Subclasses must set :attr:`name` and implement :meth:`check`. They may
    also override :attr:`critical` to mark themselves as critical — a
    failing critical check forces the overall system verdict to
    ``UNHEALTHY``.
    """

    name: str = "abstract"
    critical: bool = False

    @abc.abstractmethod
    async def check(self) -> HealthStatus:
        """Run the probe and return a :class:`HealthStatus`."""
        raise NotImplementedError


class HealthChecker:
    """Registry + concurrent runner for :class:`HealthCheck` instances.

    Typical usage::

        checker = get_health_checker()
        checker.register(DatabaseHealthCheck(critical=True))
        checker.register(RedisHealthCheck(critical=True))
        overall = await checker.overall()
    """

    def __init__(self) -> None:
        self._checks: dict[str, HealthCheck] = {}

    # ── Registration ────────────────────────────────────────────────────

    def register(self, check: HealthCheck) -> None:
        """Register a check. Re-registering under the same name replaces."""
        if not check.name or check.name == "abstract":
            raise ValueError("HealthCheck.name must be set to a non-empty identifier")
        self._checks[check.name] = check
        _log.info("health_check_registered", name=check.name, critical=check.critical)

    def unregister(self, name: str) -> None:
        """Remove a previously-registered check by name (no-op if absent)."""
        self._checks.pop(name, None)

    @property
    def checks(self) -> dict[str, HealthCheck]:
        """Read-only view of the registered checks."""
        return dict(self._checks)

    # ── Execution ───────────────────────────────────────────────────────

    async def run(self, name: str) -> HealthStatus:
        """Run a single named check.

        Any exception raised inside the check is caught and converted into
        an ``UNHEALTHY`` status — the runner must never propagate failures
        to the caller (an unhandled error would crash the probe endpoint).
        """
        check = self._checks.get(name)
        if check is None:
            return HealthStatus(
                name=name,
                status=HealthState.UNHEALTHY,
                message=f"Unknown check: {name}",
            )
        return await self._run_one(check)

    async def run_all(self) -> dict[str, HealthStatus]:
        """Run every registered check concurrently.

        Returns a mapping of ``name -> HealthStatus``. Tasks are isolated:
        a single check raising will not abort the gather.
        """
        if not self._checks:
            return {}
        results = await asyncio.gather(
            *(self._run_one(c) for c in self._checks.values()),
            return_exceptions=False,
        )
        return {status.name: status for status in results}

    async def overall(self) -> HealthStatus:
        """Compute the aggregate system status.

        Rules:

        * If *any* critical check returns ``UNHEALTHY``, the overall
          status is ``UNHEALTHY``.
        * Otherwise, if *any* check returns ``UNHEALTHY`` or
          ``DEGRADED``, the overall status is ``DEGRADED``.
        * Otherwise, the overall status is ``HEALTHY``.
        """
        all_status = await self.run_all()
        if not all_status:
            return HealthStatus(
                name="overall",
                status=HealthState.HEALTHY,
                message="No checks registered",
                details={"checks": 0},
            )

        critical_unhealthy = [
            n for n, s in all_status.items()
            if s.status == HealthState.UNHEALTHY and self._checks[n].critical
        ]
        any_degraded = any(s.status == HealthState.DEGRADED for s in all_status.values())
        any_unhealthy = any(s.status == HealthState.UNHEALTHY for s in all_status.values())

        if critical_unhealthy:
            overall_state = HealthState.UNHEALTHY
            message = f"Critical checks failing: {', '.join(critical_unhealthy)}"
        elif any_unhealthy:
            overall_state = HealthState.DEGRADED
            message = "One or more non-critical checks unhealthy"
        elif any_degraded:
            overall_state = HealthState.DEGRADED
            message = "One or more checks degraded"
        else:
            overall_state = HealthState.HEALTHY
            message = "All checks healthy"

        return HealthStatus(
            name="overall",
            status=overall_state,
            latency_ms=sum(s.latency_ms for s in all_status.values()),
            message=message,
            details={
                "checks": {n: s.status.value for n, s in all_status.items()},
                "critical_unhealthy": critical_unhealthy,
            },
        )

    # ── Internals ───────────────────────────────────────────────────────

    @staticmethod
    async def _run_one(check: HealthCheck) -> HealthStatus:
        """Execute a single check with timing + exception trapping."""
        start = time.monotonic()
        try:
            status = await check.check()
        except Exception as exc:  # noqa: BLE001 — must never propagate
            elapsed = (time.monotonic() - start) * 1000.0
            _log.exception("health_check_failed", name=check.name)
            return HealthStatus(
                name=check.name,
                status=HealthState.UNHEALTHY,
                latency_ms=elapsed,
                message=f"Check raised: {exc.__class__.__name__}: {exc}",
                details={"exception": exc.__class__.__name__},
            )
        # Backfill latency if the check forgot to set it.
        if status.latency_ms == 0.0:
            status.latency_ms = (time.monotonic() - start) * 1000.0
        return status


# ── Singleton ──────────────────────────────────────────────────────────

_checker: HealthChecker | None = None


def get_health_checker() -> HealthChecker:
    """Process-wide singleton accessor.

    The first call lazily constructs and seeds the checker with the
    platform-default probes (database, redis, bridge, risk engine, …).
    Tests can override the singleton by reassigning this module's
    ``_checker`` attribute.
    """
    global _checker
    if _checker is None:
        _checker = HealthChecker()
        _seed_defaults(_checker)
    return _checker


def _seed_defaults(checker: HealthChecker) -> None:
    """Register the platform's standard health checks.

    Imported lazily to avoid pulling heavy dependencies (psutil, redis,
    celery) at module import time — the loader should remain importable
    even when those optional deps are missing.
    """
    try:
        from platform.observability.checks import (
            BridgeHealthCheck,
            CeleryHealthCheck,
            DatabaseHealthCheck,
            DiskSpaceHealthCheck,
            MemoryHealthCheck,
            RedisHealthCheck,
            RiskEngineHealthCheck,
        )
    except ImportError:  # pragma: no cover — defensive
        _log.warning("health_checks_module_unavailable")
        return

    # Critical: the API cannot serve traffic without these.
    checker.register(DatabaseHealthCheck(critical=True))
    checker.register(RedisHealthCheck(critical=True))
    checker.register(BridgeHealthCheck(critical=True))
    checker.register(RiskEngineHealthCheck(critical=True))

    # Non-critical: degraded but not down.
    checker.register(CeleryHealthCheck())
    checker.register(DiskSpaceHealthCheck())
    checker.register(MemoryHealthCheck())
