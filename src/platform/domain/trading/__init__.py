"""Trading aggregate — Order + Position aggregates and their domain services.

This is pure business logic. Persistence is handled by repositories in
`infrastructure/`. No SQLAlchemy, no HTTP, no I/O here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timezone
from enum import StrEnum
from platform.core.exceptions import DomainError
from platform.domain.shared import (
    AggregateRoot,
    DomainEvent,
    Money,
    OrderFilled,
    OrderPlaced,
    PositionClosed,
    PositionOpened,
    Price,
    Quantity,
)
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

if TYPE_CHECKING:
    pass


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(StrEnum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class PositionStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


@dataclass(kw_only=True)
class Order(AggregateRoot):
    """Order aggregate root. Encapsulates state transitions."""

    org_id: UUID
    terminal_id: UUID
    client_order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    volume: Quantity
    price: Price | None = None
    stop_loss: Price | None = None
    take_profit: Price | None = None
    status: OrderStatus = OrderStatus.PENDING
    filled_volume: float = 0.0
    avg_fill_price: float | None = None
    strategy_id: UUID | None = None
    rejection_reason: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    submitted_at: datetime | None = None
    filled_at: datetime | None = None

    # ── State transitions ──────────────────────────────────────────────────

    def mark_submitted(self) -> None:
        if self.status not in (OrderStatus.PENDING,):
            raise DomainError(f"Cannot submit order in status {self.status}")
        self.status = OrderStatus.SUBMITTED
        self.submitted_at = datetime.now(UTC)

    def apply_fill(self, filled_volume: float, fill_price: float) -> list[DomainEvent]:
        if self.status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED):
            raise DomainError(f"Cannot fill order in status {self.status}")
        if filled_volume <= 0:
            raise DomainError("Filled volume must be positive")

        prev = self.filled_volume
        new_total = prev + filled_volume
        if new_total > self.volume.volume:
            raise DomainError(f"Fill {new_total} exceeds order volume {self.volume.volume}")
        # Update weighted average
        if self.avg_fill_price is None:
            self.avg_fill_price = fill_price
        else:
            self.avg_fill_price = (
                prev * self.avg_fill_price + filled_volume * fill_price
            ) / new_total
        self.filled_volume = new_total
        execution_id = uuid4()
        events: list[DomainEvent] = [
            OrderFilled(
                order_id=self.id,
                execution_id=execution_id,
                filled_volume=filled_volume,
                fill_price=fill_price,
            )
        ]
        if new_total == self.volume.volume:
            self.status = OrderStatus.FILLED
            self.filled_at = datetime.now(UTC)
        else:
            self.status = OrderStatus.PARTIAL
        return events

    def reject(self, reason: str) -> None:
        if self.status in (OrderStatus.FILLED, OrderStatus.CANCELLED):
            raise DomainError(f"Cannot reject order in status {self.status}")
        self.status = OrderStatus.REJECTED
        self.rejection_reason = reason

    def cancel(self) -> None:
        if self.status in (OrderStatus.FILLED, OrderStatus.REJECTED):
            raise DomainError(f"Cannot cancel order in status {self.status}")
        self.status = OrderStatus.CANCELLED

    def place(self) -> list[DomainEvent]:
        """Emit OrderPlaced event."""
        if self.status != OrderStatus.PENDING:
            raise DomainError("Order already submitted")
        self.record_event(
            OrderPlaced(
                order_id=self.id,
                terminal_id=self.terminal_id,
                symbol=self.symbol,
                side=self.side.value,
                volume=self.volume.volume,
            )
        )
        return self.collect_events()


@dataclass(kw_only=True)
class Position(AggregateRoot):
    """Position aggregate root."""

    org_id: UUID
    terminal_id: UUID
    symbol: str
    side: OrderSide
    volume: Quantity
    open_price: Price
    opened_at: datetime
    stop_loss: Price | None = None
    take_profit: Price | None = None
    current_price: Price | None = None
    swap: float = 0.0
    realized_pnl: float = 0.0
    status: PositionStatus = PositionStatus.OPEN
    closed_at: datetime | None = None
    strategy_id: UUID | None = None

    @property
    def unrealized_pnl(self) -> float:
        if self.current_price is None:
            return 0.0
        direction = 1 if self.side == OrderSide.BUY else -1
        return direction * (self.current_price.value - self.open_price.value) * self.volume.volume

    def mark_to_market(self, current: Price) -> None:
        if self.status != PositionStatus.OPEN:
            return
        self.current_price = current

    def close(self, close_price: Price) -> list[DomainEvent]:
        if self.status != PositionStatus.OPEN:
            raise DomainError("Position already closed")
        direction = 1 if self.side == OrderSide.BUY else -1
        self.realized_pnl = (
            direction * (close_price.value - self.open_price.value) * self.volume.volume
        )
        self.current_price = close_price
        self.status = PositionStatus.CLOSED
        self.closed_at = datetime.now(UTC)
        self.record_event(PositionClosed(position_id=self.id, pnl=self.realized_pnl))
        return self.collect_events()
