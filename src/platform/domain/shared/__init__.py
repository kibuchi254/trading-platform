"""DDD primitives: Entity, ValueObject, AggregateRoot, DomainEvent, Repository protocol."""
from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Generic, Protocol, TypeVar
from uuid import UUID


@dataclass(frozen=True)
class ValueObject:
    """Frozen, structurally comparable value object."""


@dataclass(eq=False)
class Entity:
    """Entity — identity is its `id`."""

    id: UUID = field(default_factory=uuid.uuid4)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Entity) and other.id == self.id

    def __hash__(self) -> int:
        return hash(self.id)


@dataclass
class DomainEvent:
    """Marker base for domain events. Subclasses add payload."""
    event_id: UUID = field(default_factory=uuid.uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class AggregateRoot(Entity):
    """Aggregate root with internal event queue for the EventBus to drain."""
    _events: list[DomainEvent] = field(default_factory=list, repr=False)

    def record_event(self, event: DomainEvent) -> None:
        self._events.append(event)

    def collect_events(self) -> list[DomainEvent]:
        events, self._events = self._events, []
        return events


T = TypeVar("T", bound=AggregateRoot)


class Repository(Protocol, Generic[T]):
    """Repository protocol — implemented per aggregate in infrastructure layer."""

    async def get(self, id: UUID) -> T | None: ...
    async def add(self, entity: T) -> T: ...
    async def save(self, entity: T) -> T: ...


# ── Common value objects ────────────────────────────────────────────────────


@dataclass(frozen=True)
class Money(ValueObject):
    amount: float
    currency: str = "USD"

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise ValueError("Money amount cannot be negative")

    def __add__(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError(f"Cannot add {self.currency} + {other.currency}")
        return Money(self.amount + other.amount, self.currency)


@dataclass(frozen=True)
class Price(ValueObject):
    value: float
    symbol_digits: int = 5

    def __post_init__(self) -> None:
        if self.value <= 0:
            raise ValueError("Price must be positive")

    @property
    def point(self) -> float:
        return 10 ** (-self.symbol_digits)


@dataclass(frozen=True)
class Quantity(ValueObject):
    volume: float
    min_step: float = 0.01

    def __post_init__(self) -> None:
        if self.volume <= 0:
            raise ValueError("Quantity must be positive")
        # Use a small epsilon to tolerate floating-point representation
        # noise (0.10 % 0.01 == 0.0099… in IEEE-754 — without this guard
        # legitimate inputs like volume=0.10 would be rejected).
        remainder = self.volume % self.min_step
        if remainder > 1e-9 and (self.min_step - remainder) > 1e-9:
            raise ValueError(f"Volume {self.volume} not aligned to step {self.min_step}")


@dataclass(frozen=True)
class Symbol(ValueObject):
    name: str
    category: str = "fx"
    digits: int = 5


@dataclass(frozen=True)
class Timeframe(ValueObject):
    code: str  # M1 | M5 | M15 | M30 | H1 | H4 | D1 | W1 | MN

    def __post_init__(self) -> None:
        valid = {"M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN"}
        if self.code not in valid:
            raise ValueError(f"Invalid timeframe: {self.code}")

    @property
    def seconds(self) -> int:
        return {
            "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
            "H1": 3600, "H4": 14400, "D1": 86400, "W1": 604800, "MN": 2592000,
        }[self.code]


# ── Domain events ───────────────────────────────────────────────────────────


@dataclass(kw_only=True)
class OrderPlaced(DomainEvent):
    order_id: UUID
    terminal_id: UUID
    symbol: str
    side: str
    volume: float


@dataclass(kw_only=True)
class OrderFilled(DomainEvent):
    order_id: UUID
    execution_id: UUID
    filled_volume: float
    fill_price: float


@dataclass(kw_only=True)
class PositionOpened(DomainEvent):
    position_id: UUID
    terminal_id: UUID
    symbol: str
    side: str
    volume: float
    open_price: float


@dataclass(kw_only=True)
class PositionClosed(DomainEvent):
    position_id: UUID
    pnl: float


@dataclass(kw_only=True)
class TerminalRegistered(DomainEvent):
    terminal_id: str
    broker: str
    account: str


@dataclass(kw_only=True)
class TerminalWentOffline(DomainEvent):
    terminal_id: str
    reason: str


@dataclass(kw_only=True)
class RiskLimitBreached(DomainEvent):
    rule: str
    severity: str
    details: dict


# Re-export for convenience
__all__ = [
    "ValueObject", "Entity", "AggregateRoot", "DomainEvent", "Repository",
    "Money", "Price", "Quantity", "Symbol", "Timeframe",
    "OrderPlaced", "OrderFilled", "PositionOpened", "PositionClosed",
    "TerminalRegistered", "TerminalWentOffline", "RiskLimitBreached",
]
