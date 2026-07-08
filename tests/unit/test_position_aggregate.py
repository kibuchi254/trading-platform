"""Test Position aggregate — pure domain logic."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from platform.core.exceptions import DomainError
from platform.domain.shared import Price, Quantity
from platform.domain.trading import OrderSide, Position, PositionStatus


def _make_position(side: OrderSide = OrderSide.BUY) -> Position:
    return Position(
        org_id=uuid4(), terminal_id=uuid4(), symbol="XAUUSD",
        side=side, volume=Quantity(volume=0.10),
        open_price=Price(value=2000.0), opened_at=datetime.now(timezone.utc),
    )


async def test_position_starts_open() -> None:
    pos = _make_position()
    assert pos.status == PositionStatus.OPEN


async def test_unrealized_pnl_zero_without_current_price() -> None:
    pos = _make_position()
    assert pos.unrealized_pnl == 0.0


async def test_mark_to_market_buy_position() -> None:
    pos = _make_position(OrderSide.BUY)
    pos.mark_to_market(Price(value=2050.0))
    # BUY: pnl = (2050 - 2000) * 0.10 = 5.0
    assert pos.unrealized_pnl == pytest.approx(5.0)


async def test_mark_to_market_sell_position() -> None:
    pos = _make_position(OrderSide.SELL)
    pos.mark_to_market(Price(value=2050.0))
    # SELL: pnl = -(2050 - 2000) * 0.10 = -5.0
    assert pos.unrealized_pnl == pytest.approx(-5.0)


async def test_close_realizes_pnl() -> None:
    pos = _make_position(OrderSide.BUY)
    events = pos.close(Price(value=2100.0))
    assert pos.status == PositionStatus.CLOSED
    assert pos.realized_pnl == pytest.approx(10.0)  # (2100-2000)*0.10
    assert pos.closed_at is not None
    assert len(events) == 1


async def test_cannot_close_already_closed() -> None:
    pos = _make_position()
    pos.close(Price(value=2000.0))
    with pytest.raises(DomainError):
        pos.close(Price(value=2000.0))


async def test_mark_to_market_ignored_on_closed_position() -> None:
    pos = _make_position()
    pos.close(Price(value=2000.0))
    pos.mark_to_market(Price(value=2050.0))
    # current_price should NOT update after close
    assert pos.current_price is not None
    assert pos.current_price.value == 2000.0
