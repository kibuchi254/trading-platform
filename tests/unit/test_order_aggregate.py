"""Test the Order aggregate — pure domain logic, no I/O."""
from __future__ import annotations

import pytest
from uuid import uuid4

from platform.core.exceptions import DomainError
from platform.domain.shared import Price, Quantity
from platform.domain.trading import Order, OrderSide, OrderStatus, OrderType


def _make_order() -> Order:
    return Order(
        org_id=uuid4(), terminal_id=uuid4(), client_order_id="test-1",
        symbol="XAUUSD", side=OrderSide.BUY, order_type=OrderType.MARKET,
        volume=Quantity(volume=0.10),
    )


async def test_order_starts_pending() -> None:
    order = _make_order()
    assert order.status == OrderStatus.PENDING


async def test_mark_submitted_transitions_status() -> None:
    order = _make_order()
    order.mark_submitted()
    assert order.status == OrderStatus.SUBMITTED
    assert order.submitted_at is not None


async def test_apply_fill_partial_then_full() -> None:
    order = _make_order()
    order.mark_submitted()
    events = order.apply_fill(0.05, 2000.00)
    assert order.status == OrderStatus.PARTIAL
    assert order.filled_volume == 0.05
    assert order.avg_fill_price == 2000.00
    assert len(events) == 1

    events = order.apply_fill(0.05, 2010.00)
    assert order.status == OrderStatus.FILLED
    assert order.filled_volume == 0.10
    assert order.avg_fill_price == pytest.approx(2005.00)
    assert order.filled_at is not None


async def test_fill_exceeds_volume_raises() -> None:
    order = _make_order()
    order.mark_submitted()
    order.apply_fill(0.05, 2000.00)
    with pytest.raises(DomainError):
        order.apply_fill(0.10, 2010.00)  # would total 0.15 > 0.10


async def test_cannot_fill_cancelled_order() -> None:
    order = _make_order()
    order.mark_submitted()
    order.cancel()
    with pytest.raises(DomainError):
        order.apply_fill(0.01, 2000.00)


async def test_reject_sets_reason() -> None:
    order = _make_order()
    order.mark_submitted()
    order.reject("insufficient_margin")
    assert order.status == OrderStatus.REJECTED
    assert order.rejection_reason == "insufficient_margin"
