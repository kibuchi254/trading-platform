"""FastAPI application factory — wires all subsystems into the lifespan.

This is the production wiring: every subsystem (event bus, registry, market
data engine, tick store, notification dispatcher, health checker, plugin
loader) is started on app startup and stopped on shutdown.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from platform.api.v1 import admin, ai, analytics, auth, market_data, orders, risk, strategies, terminals
from platform.api.ws import terminal_events, ticks
from platform.core.config import get_settings
from platform.core.exceptions import PlatformError
from platform.core.logging import configure_logging, get_logger
from platform.core.telemetry import (
    HTTP_LATENCY, HTTP_REQUESTS, setup_tracing, start_metrics_server,
)
from platform.events.bus import get_event_bus
from platform.infrastructure.mt5_bridge.registry import get_registry
from platform.observability.health import get_health_checker
from platform.observability.metrics import instrument_event_bus
from platform.observability.readiness import get_readiness_probe
from platform.strategies.builtin import ema_cross  # noqa: F401 — self-registers


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    log = get_logger("platform.main")
    settings = get_settings()
    log.info("startup_begin", env=settings.env, app=settings.app_name)

    start_metrics_server()
    setup_tracing(settings.app_name)

    # ── Event bus ────────────────────────────────────────────────────────
    bus = get_event_bus()
    await bus.connect()
    instrument_event_bus(bus)

    # ── Bridge terminal registry ─────────────────────────────────────────
    registry = get_registry()
    await registry.start_watcher()

    # ── Market data engine (subscribes to ticks) ─────────────────────────
    from platform.market_data.engine import get_market_data_engine
    market_data_engine = get_market_data_engine()
    await market_data_engine.start()

    # ── Tick store (high-throughput persistence) ─────────────────────────
    if not settings.is_production and settings.env == "test":
        log.info("skipping_tick_store_in_test_env")
    else:
        from platform.market_data.tick_store import get_tick_store
        tick_store = get_tick_store()
        await tick_store.start()

    # ── Notification dispatcher ──────────────────────────────────────────
    from platform.notifications.base import get_dispatcher
    try:
        dispatcher = get_dispatcher()
        dispatcher.subscribe_to_bus()
        log.info("notification_dispatcher_started")
    except Exception:  # noqa: BLE001
        log.warning("notification_dispatcher_failed_to_start")

    # ── Plugin loader ────────────────────────────────────────────────────
    from platform.plugins.loader import get_plugin_loader
    try:
        loader = get_plugin_loader()
        loader.load_builtin()
        log.info("plugins_loaded", counts=loader.list_plugins())
    except Exception:  # noqa: BLE001
        log.warning("plugin_loader_failed")

    # ── Risk rules ───────────────────────────────────────────────────────
    try:
        from platform.risk.engine import get_risk_engine
        from platform.risk.rules import register_all_rules
        engine = get_risk_engine()
        register_all_rules(engine)
        log.info("risk_rules_registered")
    except Exception:  # noqa: BLE001
        log.warning("risk_rules_failed_to_register")

    log.info("startup_complete")
    yield

    log.info("shutdown_begin")
    await registry.stop_watcher()

    # Stop tick store
    try:
        from platform.market_data.tick_store import get_tick_store
        await get_tick_store().stop()
    except Exception:  # noqa: BLE001
        pass

    await bus.disconnect()

    from platform.db.session import dispose_engine
    await dispose_engine()
    log.info("shutdown_complete")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="ATLAS Trading Platform",
        version="0.1.0",
        description="Enterprise AI-powered algorithmic trading platform",
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── REST routers ─────────────────────────────────────────────────────
    api_v1 = [auth, terminals, strategies, orders, ai, risk, analytics, admin, market_data]
    for r in api_v1:
        app.include_router(r.router, prefix="/api/v1")

    # ── WebSocket routers ────────────────────────────────────────────────
    app.include_router(ticks.router, prefix="/ws")
    app.include_router(terminal_events.router, prefix="/ws")

    # ── Exception handler ───────────────────────────────────────────────
    @app.exception_handler(PlatformError)
    async def platform_error_handler(request: Request, exc: PlatformError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={"code": exc.code, "message": exc.message},
        )

    # ── Metrics middleware ───────────────────────────────────────────────
    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        method = request.method
        path = request.url.path
        with HTTP_LATENCY.labels(method=method, path=path).time():
            response = await call_next(request)
        HTTP_REQUESTS.labels(method=method, path=path, status=response.status_code).inc()
        return response

    # ── Health & readiness ───────────────────────────────────────────────
    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/live", tags=["meta"])
    async def health_live() -> dict:
        probe = get_readiness_probe()
        return await probe.live()

    @app.get("/health/ready", tags=["meta"])
    async def health_ready() -> dict:
        probe = get_readiness_probe()
        return await probe.ready()

    @app.get("/health/detailed", tags=["meta"])
    async def health_detailed() -> dict:
        checker = get_health_checker()
        return {name: status.model_dump(mode="json") for name, status in (await checker.run_all()).items()}

    return app


app = create_app()
