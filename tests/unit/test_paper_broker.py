"""Test the paper broker adapter — simulated execution for backtests."""

from __future__ import annotations

from platform.infrastructure.execution.adapter_base import OrderRequest
from platform.infrastructure.execution.paper_broker import PaperBrokerAdapter

import pytest


@pytest.fixture
async def broker():
    b = PaperBrokerAdapter()
    await b.connect()
    yield b
    await b.disconnect()


async def test_market_buy_fills_at_ask(broker) -> None:
    await broker.update_ticks("XAUUSD", 2000.0, 2000.5)
    req = OrderRequest(
        client_order_id="test-1",
        symbol="XAUUSD",
        side="buy",
        order_type="market",
        volume=0.10,
    )
    report = await broker.place_order(req)
    assert report.status == "filled"
    assert report.filled_volume == 0.10
    assert report.avg_price == 2000.5  # ask


async def test_market_sell_fills_at_bid(broker) -> None:
    await broker.update_ticks("XAUUSD", 2000.0, 2000.5)
    req = OrderRequest(
        client_order_id="test-2",
        symbol="XAUUSD",
        side="sell",
        order_type="market",
        volume=0.05,
    )
    report = await broker.place_order(req)
    assert report.status == "filled"
    assert report.avg_price == 2000.0  # bid


async def test_limit_order_pending_until_crossed(broker) -> None:
    await broker.update_ticks("XAUUSD", 2000.0, 2000.5)
    req = OrderRequest(
        client_order_id="test-3",
        symbol="XAUUSD",
        side="buy",
        order_type="limit",
        volume=0.10,
        price=1995.0,
    )
    report = await broker.place_order(req)
    assert report.status == "accepted"
    # Price drops to 1994 → limit triggers
    await broker.update_ticks("XAUUSD", 1994.0, 1994.5)
    # Position should now be open
    positions = await broker.sync_positions()
    assert any(p.symbol == "XAUUSD" for p in positions)


async def test_close_position_realizes_pnl(broker) -> None:
    await broker.update_ticks("XAUUSD", 2000.0, 2000.5)
    req = OrderRequest(
        client_order_id="test-4",
        symbol="XAUUSD",
        side="buy",
        order_type="market",
        volume=0.10,
    )
    await broker.place_order(req)

    positions = await broker.sync_positions()
    assert len(positions) == 1
    pos_id = positions[0].broker_position_id

    # Price moves up 50 points → +$5 unrealized
    await broker.update_ticks("XAUUSD", 2050.0, 2050.5)
    positions = await broker.sync_positions()
    assert positions[0].unrealized_pnl > 0

    # Close
    report = await broker.close_position(pos_id)
    assert report.status == "filled"

    # Account should reflect realized PnL
    account = await broker.sync_account()
    assert account.balance == pytest.approx(10005.0, abs=0.5)


async def test_account_snapshot(broker) -> None:
    account = await broker.sync_account()
    assert account.balance == 10_000.0
    assert account.equity == 10_000.0
    assert account.currency == "USD"


async def test_disconnect_clears_state(broker) -> None:
    await broker.update_ticks("XAUUSD", 2000.0, 2000.5)
    req = OrderRequest(
        client_order_id="test-5",
        symbol="XAUUSD",
        side="buy",
        order_type="market",
        volume=0.10,
    )
    await broker.place_order(req)
    await broker.disconnect()
    assert len(broker._positions) == 0
    assert len(broker._orders) == 0
