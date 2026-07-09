"""PlaceOrder command — the canonical use case showing the full vertical slice:

  API layer  →  command  →  risk check  →  bridge.place_order
                                          →  execution report handler
                                          →  order/position persistence

This file shows the pattern. Every other use case follows the same shape.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from platform.core.exceptions import ValidationError
from platform.core.logging import get_logger
from platform.db.models import Order as OrderModel
from platform.db.models import Terminal
from platform.db.session import db_context
from platform.domain.shared import Price, Quantity
from platform.domain.trading import Order, OrderSide, OrderStatus, OrderType
from platform.infrastructure.mt5_bridge.client import get_bridge_client
from platform.risk.engine import get_risk_engine
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select

_log = get_logger(__name__)


# ── Command + DTO ──────────────────────────────────────────────────────────


class PlaceOrderCommand(BaseModel):
    org_id: UUID
    user_id: UUID
    terminal_id: str  # external terminal_id
    symbol: str
    side: str  # buy | sell
    order_type: str  # market | limit | stop | stop_limit
    volume: float
    price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    strategy_id: UUID | None = None
    comment: str | None = None
    magic: int | None = None


class PlaceOrderResult(BaseModel):
    order_id: UUID
    client_order_id: str
    broker_order_id: str | None = None
    status: str
    filled_volume: float = 0.0
    avg_fill_price: float | None = None
    rejection_reason: str | None = None


# ── Handler ─────────────────────────────────────────────────────────────────


async def handle_place_order(cmd: PlaceOrderCommand) -> PlaceOrderResult:
    """Orchestrates: validate → risk check → persist pending → bridge → result."""
    from platform.core.telemetry import ORDERS_PLACED

    # 1. Validate
    try:
        side = OrderSide(cmd.side.lower())
        order_type = OrderType(cmd.order_type.lower())
    except ValueError as e:
        raise ValidationError(str(e)) from e

    if cmd.volume <= 0:
        raise ValidationError("Volume must be positive")
    if order_type != OrderType.MARKET and cmd.price is None:
        raise ValidationError(f"{order_type} order requires price")

    # 2. Risk pre-check (synchronous, fast)
    risk = get_risk_engine()
    await risk.check_order(
        org_id=cmd.org_id,
        terminal_id=cmd.terminal_id,
        symbol=cmd.symbol,
        side=cmd.side,
        volume=cmd.volume,
        price=cmd.price,
    )

    # 3. Persist Order in PENDING state (transaction script)
    client_order_id = f"atlas-{uuid.uuid4().hex[:12]}"
    order = Order(
        org_id=cmd.org_id,
        terminal_id=uuid.uuid4(),  # placeholder, replaced below
        client_order_id=client_order_id,
        symbol=cmd.symbol,
        side=side,
        order_type=order_type,
        volume=Quantity(volume=cmd.volume),
        price=Price(value=cmd.price) if cmd.price else None,
        stop_loss=Price(value=cmd.stop_loss) if cmd.stop_loss else None,
        take_profit=Price(value=cmd.take_profit) if cmd.take_profit else None,
        strategy_id=cmd.strategy_id,
    )
    order.record_event  # noqa: B018 (just ensures aggregate loaded)
    order.place()

    async with db_context() as db:
        # Resolve internal terminal id from external terminal_id
        terminal = (
            await db.execute(
                select(Terminal).where(
                    Terminal.terminal_id == cmd.terminal_id, Terminal.org_id == cmd.org_id
                )
            )
        ).scalar_one_or_none()
        if terminal is None:
            raise ValidationError(f"Terminal {cmd.terminal_id} not found")

        model = OrderModel(
            org_id=cmd.org_id,
            terminal_id=terminal.id,
            strategy_id=cmd.strategy_id,
            client_order_id=client_order_id,
            symbol=cmd.symbol,
            side=cmd.side,
            order_type=cmd.order_type,
            volume=cmd.volume,
            price=cmd.price,
            stop_loss=cmd.stop_loss,
            take_profit=cmd.take_profit,
            status=OrderStatus.PENDING.value,
        )
        db.add(model)
        await db.commit()
        await db.refresh(model)
        order_id = model.id

    # 4. Dispatch to MT5 Bridge — this BLOCKS until the terminal acks
    bridge = get_bridge_client()
    try:
        reply = await bridge.place_order(
            terminal_id=cmd.terminal_id,
            symbol=cmd.symbol,
            side=cmd.side,
            order_type=cmd.order_type,
            volume=cmd.volume,
            price=cmd.price,
            stop_loss=cmd.stop_loss,
            take_profit=cmd.take_profit,
            client_order_id=client_order_id,
            comment=cmd.comment,
            magic=cmd.magic,
        )
    except Exception as e:
        # Mark order as rejected in DB
        async with db_context() as db:
            db_order = await db.get(OrderModel, order_id)
            if db_order:
                db_order.status = OrderStatus.REJECTED.value
                db_order.rejection_reason = f"bridge_error: {e}"
                await db.commit()
        raise

    # 5. Interpret reply → update Order row
    status_str = reply.payload.get("status", "submitted")
    broker_order_id = reply.payload.get("broker_order_id")
    filled_volume = float(reply.payload.get("filled_volume", 0))
    avg_price = reply.payload.get("avg_price")
    rejection = reply.payload.get("rejection_reason")

    final_status = _map_status(status_str)
    async with db_context() as db:
        db_order = await db.get(OrderModel, order_id)
        if db_order:
            db_order.status = final_status
            db_order.broker_order_id = broker_order_id
            db_order.filled_volume = filled_volume
            if avg_price is not None:
                db_order.avg_fill_price = float(avg_price)
            db_order.rejection_reason = rejection
            if final_status in (OrderStatus.FILLED.value, OrderStatus.PARTIAL.value):
                db_order.filled_at = datetime.now(UTC)
            await db.commit()

    ORDERS_PLACED.labels(terminal_id=cmd.terminal_id, symbol=cmd.symbol, side=cmd.side).inc()

    return PlaceOrderResult(
        order_id=order_id,
        client_order_id=client_order_id,
        broker_order_id=broker_order_id,
        status=final_status,
        filled_volume=filled_volume,
        avg_fill_price=float(avg_price) if avg_price is not None else None,
        rejection_reason=rejection,
    )


def _map_status(s: str) -> str:
    return {
        "accepted": OrderStatus.SUBMITTED.value,
        "partial": OrderStatus.PARTIAL.value,
        "filled": OrderStatus.FILLED.value,
        "cancelled": OrderStatus.CANCELLED.value,
        "rejected": OrderStatus.REJECTED.value,
    }.get(s, OrderStatus.SUBMITTED.value)
