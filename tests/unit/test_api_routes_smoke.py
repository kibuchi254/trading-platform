"""HTTP smoke test for the REST surface.

Boots the FastAPI app in-process (httpx ASGITransport — no network, no DB, no
Redis needed: auth-required routes return 401 *before* any DB access, and the
docs/health endpoints don't touch the DB).

The point: every route the admin console calls must exist on the backend
(401 = "exists, needs auth"; 200 for docs/health). A 404 means the router is
missing — i.e. frontend↔backend drift. This runs in the unit-tests CI job, so
such drift fails the build on the PR that introduces it.

The route list below mirrors `frontend/src/lib/api/endpoints.ts` — update both
together when you add or rename an endpoint.
"""

from __future__ import annotations

from platform.main import app

import httpx
import pytest

# Fully public — must return 200.
PUBLIC_OK = ["/docs", "/openapi.json", "/health"]

# Public health probes — must exist (not 404). /ready may report 503 if a
# dependency is down, which is fine; we only assert the route is wired.
PUBLIC_EXISTS = ["/health/live", "/health/ready"]

# Auth-required GET routes — no auth header → 401 (never 404). This is the set
# the console's endpoints.ts calls.
AUTHED_GET = [
    "/api/v1/auth/me",
    "/api/v1/terminals",
    "/api/v1/orders",
    "/api/v1/positions",
    "/api/v1/trades",
    "/api/v1/signals",
    "/api/v1/risk-events",
    "/api/v1/risk/kill-switch",
    "/api/v1/backtests",
    "/api/v1/notifications",
    "/api/v1/brokers",
    "/api/v1/strategies",
    "/api/v1/strategies/available",
    "/api/v1/market-data/symbols",
    "/api/v1/analytics/performance",
    "/api/v1/analytics/positions/open",
    "/api/v1/admin/status",
    "/api/v1/admin/users",
    "/api/v1/admin/audit-logs",
]

# Public POST routes (login/register/refresh) — no body → 4xx validation, never 404.
PUBLIC_POST = ["/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/auth/refresh"]

# Auth-required POST routes — no auth header → 401, never 404.
AUTHED_POST = [
    "/api/v1/orders",
    "/api/v1/strategies",
    "/api/v1/backtests",
    "/api/v1/brokers",
    "/api/v1/auth/api-keys?name=ci",
    "/api/v1/risk/kill-switch/engage",
]


@pytest.fixture(scope="module")
async def client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.parametrize("path", PUBLIC_OK)
async def test_public_endpoints_return_ok(client: httpx.AsyncClient, path: str) -> None:
    r = await client.get(path)
    assert r.status_code == 200, f"{path} → {r.status_code}"


@pytest.mark.parametrize("path", PUBLIC_EXISTS)
async def test_health_probes_exist(client: httpx.AsyncClient, path: str) -> None:
    r = await client.get(path)
    assert r.status_code != 404, f"{path} → 404 (route missing)"


@pytest.mark.parametrize("path", AUTHED_GET)
async def test_authed_get_routes_exist(client: httpx.AsyncClient, path: str) -> None:
    r = await client.get(path)  # no Authorization / X-API-Key header
    assert r.status_code == 401, (
        f"{path} → {r.status_code} (expected 401 = exists & needs auth; 404 = missing router)"
    )


@pytest.mark.parametrize("path", PUBLIC_POST)
async def test_public_post_routes_exist(client: httpx.AsyncClient, path: str) -> None:
    r = await client.post(path)  # no body
    assert r.status_code != 404, f"{path} → 404 (route missing)"
    # 422 (validation) or 401 — both prove the route is wired.
    assert r.status_code >= 400, f"{path} → {r.status_code} (expected a 4xx)"


@pytest.mark.parametrize("path", AUTHED_POST)
async def test_authed_post_routes_exist(client: httpx.AsyncClient, path: str) -> None:
    r = await client.post(path)  # no auth header
    assert r.status_code == 401, (
        f"{path} → {r.status_code} (expected 401 = exists & needs auth; 404 = missing router)"
    )


async def test_openapi_lists_all_expected_paths() -> None:
    """Belt-and-braces: the OpenAPI schema must advertise every console path."""
    expected = {
        "/api/v1/auth/me",
        "/api/v1/terminals",
        "/api/v1/orders",
        "/api/v1/positions",
        "/api/v1/trades",
        "/api/v1/signals",
        "/api/v1/risk-events",
        "/api/v1/backtests",
        "/api/v1/notifications",
        "/api/v1/brokers",
        "/api/v1/admin/users",
        "/api/v1/admin/audit-logs",
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        spec = (await c.get("/openapi.json")).json()
    paths = set(spec.get("paths", {}).keys())
    missing = expected - paths
    assert not missing, f"OpenAPI missing paths (frontend would 404): {sorted(missing)}"
