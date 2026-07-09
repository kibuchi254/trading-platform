"""Test the EventBus — local-only mode (no Redis)."""

from __future__ import annotations

from platform.events.bus import EventBus

import pytest


@pytest.fixture
def bus():
    b = EventBus()
    b._local_only = True
    return b


async def test_local_publish_invokes_subscribers(bus) -> None:
    received = []

    async def handler(payload):
        received.append(payload)

    bus.subscribe("test.topic", handler)
    await bus.publish("test.topic", {"msg": "hello"})
    assert len(received) == 1
    assert received[0]["msg"] == "hello"


async def test_multiple_subscribers_all_invoked(bus) -> None:
    received_a = []
    received_b = []

    async def handler_a(payload):
        received_a.append(payload)

    async def handler_b(payload):
        received_b.append(payload)

    bus.subscribe("test.topic", handler_a)
    bus.subscribe("test.topic", handler_b)
    await bus.publish("test.topic", {"msg": "broadcast"})
    assert len(received_a) == 1
    assert len(received_b) == 1


async def test_handler_exception_does_not_break_others(bus) -> None:
    received = []

    async def failing_handler(payload):
        raise RuntimeError("boom")

    async def good_handler(payload):
        received.append(payload)

    bus.subscribe("test.topic", failing_handler)
    bus.subscribe("test.topic", good_handler)
    # Should not raise
    await bus.publish("test.topic", {"msg": "test"})
    assert len(received) == 1


async def test_unsubscribed_topic_no_handlers(bus) -> None:
    # Publishing to a topic with no subscribers should not raise
    await bus.publish("nobody.listening", {"msg": "hello"})
    # No assertions needed — just shouldn't crash


async def test_subscribe_after_first_publish_does_not_get_old_messages(bus) -> None:
    received = []

    await bus.publish("test.topic", {"msg": "first"})

    async def handler(payload):
        received.append(payload)

    bus.subscribe("test.topic", handler)
    await bus.publish("test.topic", {"msg": "second"})
    # Should only receive "second"
    assert len(received) == 1
    assert received[0]["msg"] == "second"
