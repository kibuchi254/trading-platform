"""Tests for the HTTP bridge router (`/api/v1/bridge-http/*).

Covers the fixes that make HTTP-polling MT5 terminals work end-to-end:
- /poll caches the account snapshot in the registry + publishes ACCOUNT_UPDATES
- /tick publishes TICKS (so the market-data engine + /ws/ticks work)
- /poll drains queued outbound commands (HTTP command delivery)
- /report resolves a pending place_order by client_order_id correlation
"""

from __future__ import annotations

import asyncio
import platform.api.v1.bridge_http as bridge_http
from platform.events.bus import get_event_bus
from platform.events.topics import Topic
from platform.infrastructure.mt5_bridge.command_queue import get_command_queue
from platform.infrastructure.mt5_bridge.protocol import CommandType, command
from platform.infrastructure.mt5_bridge.registry import get_registry
from platform.main import app

import httpx
import pytest


async def _noop_persist(terminal_id: str, snapshot: dict) -> None:  # type: ignore[no-untyped-def]
    return None


@pytest.fixture
async def client(local_only_bus, clean_registry, monkeypatch):
    monkeypatch.setattr(bridge_http, "_persist_account", _noop_persist)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _register(client: httpx.AsyncClient, terminal_id: str) -> None:
    r = await client.post(
        "/api/v1/bridge-http/register",
        json={
            "terminal_id": terminal_id,
            "broker": "Exness",
            "account": 12345,
            "version": "2.00",
            "symbols": ["EURUSD", "XAUUSD"],
            "auth_token": "tok",
        },
    )
    assert r.status_code == 200


async def test_poll_caches_account_and_publishes(client: httpx.AsyncClient) -> None:
    await _register(client, "mt5-poll-01")

    captured: list[dict] = []

    async def capture(payload: dict) -> None:
        captured.append(payload)

    get_event_bus().subscribe(Topic.ACCOUNT_UPDATES, capture)

    r = await client.post(
        "/api/v1/bridge-http/poll",
        json={
            "terminal_id": "mt5-poll-01",
            "balance": 10000.0,
            "equity": 10100.0,
            "margin": 200.0,
            "free_margin": 9900.0,
            "currency": "USD",
            "leverage": 100,
        },
    )
    assert r.status_code == 200

    # Cached on the registry record (so sync-account / GET account work).
    snapshot = await get_registry().get_account("mt5-poll-01")
    assert snapshot is not None
    assert snapshot["balance"] == 10000.0
    assert snapshot["equity"] == 10100.0
    assert snapshot["currency"] == "USD"

    # Published to the bus (so /ws/account streams live).
    assert len(captured) == 1
    assert captured[0]["balance"] == 10000.0


async def test_tick_publishes_to_bus(client: httpx.AsyncClient) -> None:
    await _register(client, "mt5-tick-01")

    captured: list[dict] = []

    async def capture(payload: dict) -> None:
        captured.append(payload)

    get_event_bus().subscribe(Topic.TICKS, capture)

    r = await client.post(
        "/api/v1/bridge-http/tick",
        json={
            "terminal_id": "mt5-tick-01",
            "symbol": "EURUSD",
            "bid": 1.08,
            "ask": 1.0801,
            "last": 1.08005,
            "volume": 0.0,
        },
    )
    assert r.status_code == 200
    assert len(captured) == 1
    assert captured[0]["symbol"] == "EURUSD"
    assert captured[0]["bid"] == 1.08


async def test_poll_drains_outbound_commands(client: httpx.AsyncClient) -> None:
    await _register(client, "mt5-outbox-01")
    registry = get_registry()

    cmd = command(
        CommandType.PLACE_ORDER,
        terminal_id="mt5-outbox-01",
        payload={"client_order_id": "coid-1", "symbol": "EURUSD"},
    )
    await registry.enqueue_outbound("mt5-outbox-01", cmd)

    r = await client.post(
        "/api/v1/bridge-http/poll",
        json={
            "terminal_id": "mt5-outbox-01",
            "balance": 0,
            "equity": 0,
            "margin": 0,
            "free_margin": 0,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    commands = body["commands"]
    assert len(commands) == 1
    assert commands[0]["t"] == "cmd.order.place"
    assert commands[0]["payload"]["client_order_id"] == "coid-1"

    # Outbox is drained — a second poll returns no commands.
    r2 = await client.post(
        "/api/v1/bridge-http/poll",
        json={
            "terminal_id": "mt5-outbox-01",
            "balance": 0,
            "equity": 0,
            "margin": 0,
            "free_margin": 0,
        },
    )
    assert r2.json()["commands"] == []


async def test_report_resolves_pending_place_order(client: httpx.AsyncClient) -> None:
    await _register(client, "mt5-rpt-01")
    queue = get_command_queue()

    cmd = command(
        CommandType.PLACE_ORDER,
        terminal_id="mt5-rpt-01",
        payload={"client_order_id": "coid-9", "symbol": "EURUSD", "side": "buy"},
    )
    await queue.register_correlation("coid-9", cmd.id)
    # enqueue() awaits the future; run it in the background.
    task = asyncio.create_task(queue.enqueue(cmd, timeout=5.0))
    await asyncio.sleep(0.05)  # let the pending entry register

    r = await client.post(
        "/api/v1/bridge-http/report",
        json={
            "terminal_id": "mt5-rpt-01",
            "event_type": "evt.order.filled",
            "payload": {
                "client_order_id": "coid-9",
                "broker_order_id": "B001",
                "status": "filled",
                "filled_volume": 0.1,
                "avg_price": 1.1,
                "rejection_reason": "",
            },
        },
    )
    assert r.status_code == 200

    reply = await asyncio.wait_for(task, timeout=2.0)
    assert reply.t == "evt.order.filled"
    assert reply.payload["client_order_id"] == "coid-9"
