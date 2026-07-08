"""Readiness + liveness probes for Kubernetes-style orchestrators.

Two distinct concepts map to two endpoints:

* **Liveness** (``/health/live``) — *is the process alive?* Should be
  cheap, dependency-free, and never fail unless the process is wedged.
  A failing liveness probe triggers a pod restart.

* **Readiness** (``/health/ready``) — *is the process ready to serve
  traffic?* Verifies that every dependency needed to handle a request
  is reachable. A failing readiness probe removes the pod from the
  service's endpoint list (drain) but does *not* restart it.

Readiness rule
--------------
The platform is considered ready when:

1. The database is reachable (``SELECT 1`` succeeds).
2. Redis is reachable (``PING`` returns ``True``).
3. At least one MT5 terminal is online (configurable via
   :attr:`ReadinessProbe.min_terminals`).

If any of those conditions fail, the probe returns
``{"ready": False, "checks": {...}}`` with HTTP 503 — the load balancer
will stop sending traffic. Liveness always returns 200 with a timestamp
so the orchestrator knows the loop is responsive.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from platform.core.logging import get_logger

_log = get_logger(__name__)


class ReadinessProbe:
    """Liveness + readiness probe for the ATLAS API process.

    Parameters
    ----------
    min_terminals:
        Minimum number of online MT5 terminals required for readiness.
        Defaults to 1; set to 0 to skip the bridge check (useful for
        headless worker processes that don't route orders).
    """

    def __init__(self, min_terminals: int = 1) -> None:
        self.min_terminals = max(0, min_terminals)

    # ── Liveness ────────────────────────────────────────────────────────

    async def live(self) -> dict[str, Any]:
        """Liveness probe — always succeeds unless the event loop is wedged.

        Returns
        -------
        dict
            ``{"alive": True, "ts": <iso8601 utc>}``
        """
        return {
            "alive": True,
            "ts": datetime.now(timezone.utc).isoformat(),
        }

    # ── Readiness ───────────────────────────────────────────────────────

    async def ready(self) -> dict[str, Any]:
        """Readiness probe — verify every hard dependency.

        Returns
        -------
        dict
            ``{"ready": bool, "checks": {name: {ok, latency_ms, detail}}, "ts": ...}``
        """
        checks: dict[str, dict[str, Any]] = {}
        start = time.monotonic()

        db_ok = await self._check_database(checks)
        redis_ok = await self._check_redis(checks)
        bridge_ok = await self._check_bridge(checks)

        ready = db_ok and redis_ok and bridge_ok
        elapsed_ms = (time.monotonic() - start) * 1000.0
        _log.debug(
            "readiness_probe_complete",
            ready=ready,
            db=db_ok,
            redis=redis_ok,
            bridge=bridge_ok,
            elapsed_ms=elapsed_ms,
        )
        return {
            "ready": ready,
            "checks": checks,
            "elapsed_ms": round(elapsed_ms, 2),
            "ts": datetime.now(timezone.utc).isoformat(),
        }

    # ── Individual checks ───────────────────────────────────────────────

    async def _check_database(self, out: dict[str, dict[str, Any]]) -> bool:
        """Run ``SELECT 1`` and record the result."""
        start = time.monotonic()
        try:
            from sqlalchemy import text

            from platform.db.session import db_context

            async with db_context() as session:
                value = (await session.execute(text("SELECT 1"))).scalar_one_or_none()
            latency_ms = (time.monotonic() - start) * 1000.0
            ok = value == 1
            out["database"] = {
                "ok": ok,
                "latency_ms": round(latency_ms, 2),
                "detail": "SELECT 1 succeeded" if ok else f"unexpected scalar: {value!r}",
            }
            return ok
        except Exception as exc:  # noqa: BLE001
            latency_ms = (time.monotonic() - start) * 1000.0
            out["database"] = {
                "ok": False,
                "latency_ms": round(latency_ms, 2),
                "detail": f"{exc.__class__.__name__}: {exc}",
            }
            return False

    async def _check_redis(self, out: dict[str, dict[str, Any]]) -> bool:
        """Run ``PING`` against the configured Redis URL."""
        start = time.monotonic()
        try:
            import redis.asyncio as aioredis

            from platform.core.config import get_settings

            settings = get_settings()
            client = aioredis.from_url(settings.redis_url, decode_responses=True)
            try:
                pong = await client.ping()
            finally:
                await client.aclose()
            latency_ms = (time.monotonic() - start) * 1000.0
            out["redis"] = {
                "ok": bool(pong),
                "latency_ms": round(latency_ms, 2),
                "detail": "PING ok" if pong else "PING returned False",
            }
            return bool(pong)
        except Exception as exc:  # noqa: BLE001
            latency_ms = (time.monotonic() - start) * 1000.0
            out["redis"] = {
                "ok": False,
                "latency_ms": round(latency_ms, 2),
                "detail": f"{exc.__class__.__name__}: {exc}",
            }
            return False

    async def _check_bridge(self, out: dict[str, dict[str, Any]]) -> bool:
        """Count online terminals and require at least :attr:`min_terminals`."""
        if self.min_terminals == 0:
            out["bridge"] = {
                "ok": True,
                "latency_ms": 0.0,
                "detail": "bridge check disabled (min_terminals=0)",
            }
            return True
        start = time.monotonic()
        try:
            from platform.infrastructure.mt5_bridge.registry import get_registry

            terminals = await get_registry().list_online()
            latency_ms = (time.monotonic() - start) * 1000.0
            count = len(terminals)
            ok = count >= self.min_terminals
            out["bridge"] = {
                "ok": ok,
                "latency_ms": round(latency_ms, 2),
                "detail": (
                    f"{count} terminal(s) online (min {self.min_terminals})"
                    if ok else
                    f"only {count} terminal(s) online (min {self.min_terminals})"
                ),
                "terminals_online": count,
            }
            return ok
        except Exception as exc:  # noqa: BLE001
            latency_ms = (time.monotonic() - start) * 1000.0
            out["bridge"] = {
                "ok": False,
                "latency_ms": round(latency_ms, 2),
                "detail": f"{exc.__class__.__name__}: {exc}",
            }
            return False


# ── Singleton ──────────────────────────────────────────────────────────

_probe: ReadinessProbe | None = None


def get_readiness_probe() -> ReadinessProbe:
    """Process-wide singleton accessor for the readiness probe."""
    global _probe
    if _probe is None:
        _probe = ReadinessProbe()
    return _probe
