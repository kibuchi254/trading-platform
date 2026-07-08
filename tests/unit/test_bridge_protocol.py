"""Test the bridge protocol — verify message envelope + typed payloads."""
from __future__ import annotations

from datetime import datetime, timezone

from platform.infrastructure.mt5_bridge.protocol import (
    CommandType, EventType, BridgeMessage, PlaceOrderPayload, TickPayload,
    command, event, ack,
)


def test_command_envelope_has_correct_type() -> None:
    msg = command(CommandType.PLACE_ORDER, terminal_id="t1", payload={"symbol": "XAUUSD"})
    assert msg.t == "cmd.order.place"
    assert msg.terminal_id == "t1"
    assert msg.v == 1
    assert msg.id  # auto-generated uuid


def test_event_envelope_has_correct_type() -> None:
    msg = event(EventType.TICK, terminal_id="t1",
                payload={"symbol": "XAUUSD", "bid": 2000.0, "ask": 2000.5, "ts": "2026-01-01T00:00:00Z"})
    assert msg.t == "evt.tick"


def test_ack_carries_reply_to() -> None:
    original = command(CommandType.PLACE_ORDER, terminal_id="t1", payload={})
    reply = ack(original, payload={"status": "filled"})
    assert reply.reply_to == original.id
    assert reply.t == original.t


def test_place_order_payload_validates() -> None:
    p = PlaceOrderPayload(
        client_order_id="atlas-1", symbol="XAUUSD", side="buy",
        order_type="market", volume=0.10,
    )
    assert p.symbol == "XAUUSD"
    assert p.stop_loss is None


def test_tick_payload_serializes() -> None:
    p = TickPayload(symbol="EURUSD", bid=1.08, ask=1.0801, ts=datetime.now(timezone.utc))
    msg = event(EventType.TICK, terminal_id="t1", payload=p.model_dump(mode="json"))
    # Round-trip
    decoded = BridgeMessage.model_validate(msg.model_dump())
    assert decoded.payload["symbol"] == "EURUSD"
