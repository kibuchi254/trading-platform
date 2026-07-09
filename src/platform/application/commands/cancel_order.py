"""Cancel an open (pending / submitted / partial) order.

Vertical slice:

  API → command → load Order row → bridge.cancel_order
                              → update Order status (cancelled / still active)
                              → publish ORDERS event

Follows the same shape as :mod:`platform.application.commands.place_order`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from platform.core.exceptions import NotFoundError, ValidationError
from platform.core.logging import get_logger
from platform.db.models import Order as OrderModel
from platform.db.session import db_context
from platform.events.bus import get_event_bus
from platform.events.topics import Topic
from platform.infrastructure.mt5_bridge.client import get_bridge_client
from uuid import UUID

from pydantic import BaseModel

_log = get_logger(__name__)

# Statuses that are already terminal and cannot be cancelled.
_TERMINAL_STATUSES = frozenset({"filled", "cancelled", "rejected"})


# ── Command + DTO ──────────────────────────────────────────────────────────


class CancelOrderCommand(BaseModel):
    org_id: UUID
    user_id: UUID
    order_id: UUID
    terminal_id: str  # external terminal_id


class CancelOrderResult(BaseModel):
    order_id: UUID
    client_order_id: str
    status: str
    broker_order_id: str | None = None
    cancelled_at: str | None = None


# ── Handler ─────────────────────────────────────────────────────────────────


async def handle_cancel_order(cmd: CancelOrderCommand) -> CancelOrderResult:
    """Load the order, ask the bridge to cancel it, persist final state."""
    async with db_context() as db:
        order = await db.get(OrderModel, cmd.order_id)
        if order is None or order.org_id != cmd.org_id:
            raise NotFoundError(f"Order {cmd.order_id} not found")

        if order.status in _TERMINAL_STATUSES:
            raise ValidationError(f"Cannot cancel order in status {order.status}")
        if not order.broker_order_id:
            raise ValidationError("Order has no broker_order_id yet — not yet on broker")

        bridge = get_bridge_client()
        reply = await bridge.cancel_order(
            terminal_id=cmd.terminal_id,
            broker_order_id=order.broker_order_id,
        )

        remote_status = reply.payload.get("status", "cancelled")
        now = datetime.now(UTC)
        if remote_status in ("cancelled", "rejected"):
            order.status = "cancelled"
            order.rejection_reason = reply.payload.get("rejection_reason")
            order.filled_at = now if remote_status == "cancelled" else order.filled_at
        # If the broker replied with a non-cancellable status (e.g. filled),
        # we surface the broker's truth rather than silently overriding.
        order.updated_at = now
        await db.commit()

        result = CancelOrderResult(
            order_id=order.id,
            client_order_id=order.client_order_id,
            status=order.status,
            broker_order_id=order.broker_order_id,
            cancelled_at=now.isoformat() if order.status == "cancelled" else None,
        )

    await get_event_bus().publish(
        Topic.ORDERS,
        {
            "type": "order_cancelled",
            "org_id": str(cmd.org_id),
            "order_id": str(result.order_id),
            "client_order_id": result.client_order_id,
            "broker_order_id": result.broker_order_id,
            "status": result.status,
            "actor_id": str(cmd.user_id),
        },
    )
    _log.info(
        "order_cancelled",
        order_id=str(result.order_id),
        terminal_id=cmd.terminal_id,
        status=result.status,
    )
    return result
