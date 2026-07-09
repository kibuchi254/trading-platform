"""Test the HealthChecker — register, run_all, overall status aggregation."""

from __future__ import annotations

import asyncio
from platform.observability.health import HealthCheck, HealthChecker, HealthStatus


class AlwaysHealthy(HealthCheck):
    name = "always_healthy"

    async def check(self) -> HealthStatus:
        return HealthStatus(
            name=self.name, status="HEALTHY", latency_ms=1.0, message="ok", details={}
        )


class AlwaysDegraded(HealthCheck):
    name = "always_degraded"

    async def check(self) -> HealthStatus:
        return HealthStatus(
            name=self.name, status="DEGRADED", latency_ms=10.0, message="slow", details={}
        )


class AlwaysUnhealthy(HealthCheck):
    name = "always_unhealthy"

    async def check(self) -> HealthStatus:
        return HealthStatus(
            name=self.name, status="UNHEALTHY", latency_ms=0, message="down", details={}
        )


class FailingCheck(HealthCheck):
    name = "failing"

    async def check(self) -> HealthStatus:
        raise RuntimeError("check failed")


async def test_register_and_run_single() -> None:
    checker = HealthChecker()
    checker.register(AlwaysHealthy())
    result = await checker.run("always_healthy")
    assert result.status == "HEALTHY"


async def test_run_all_concurrent() -> None:
    """All checks should run concurrently via asyncio.gather."""
    checker = HealthChecker()

    class SlowCheck(HealthCheck):
        name = "slow"

        async def check(self) -> HealthStatus:
            await asyncio.sleep(0.1)
            return HealthStatus(
                name=self.name, status="HEALTHY", latency_ms=100, message="ok", details={}
            )

    checker.register(SlowCheck())
    # Register 5 of them
    for i in range(5):
        c = SlowCheck()
        c.name = f"slow_{i}"
        checker.register(c)

    import time

    start = time.monotonic()
    results = await checker.run_all()
    elapsed = time.monotonic() - start
    # If concurrent, total time ~0.1s, not 0.6s
    assert elapsed < 0.3
    assert len(results) == 6


async def test_overall_healthy_when_all_healthy() -> None:
    checker = HealthChecker()
    checker.register(AlwaysHealthy())
    overall = await checker.overall()
    assert overall.status == "HEALTHY"


async def test_overall_degraded_when_any_degraded() -> None:
    checker = HealthChecker()
    checker.register(AlwaysHealthy())
    checker.register(AlwaysDegraded())
    overall = await checker.overall()
    assert overall.status == "DEGRADED"


async def test_overall_unhealthy_when_any_unhealthy() -> None:
    checker = HealthChecker()
    checker.register(AlwaysHealthy())
    checker.register(AlwaysDegraded())
    
    # Non-critical unhealthy check only degrades the system.
    # To force overall UNHEALTHY status, the check must be marked critical.
    class AlwaysUnhealthyCritical(AlwaysUnhealthy):
        critical = True
        
    checker.register(AlwaysUnhealthyCritical())
    overall = await checker.overall()
    assert overall.status == "UNHEALTHY"


async def test_failing_check_returns_unhealthy() -> None:
    """A check that raises should be caught and return UNHEALTHY, not propagate."""
    checker = HealthChecker()
    checker.register(FailingCheck())
    result = await checker.run("failing")
    assert result.status == "UNHEALTHY"
    assert "check failed" in result.message or "RuntimeError" in result.message
