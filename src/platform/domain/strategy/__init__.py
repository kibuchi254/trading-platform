"""Strategy bounded context — Signal + Strategy aggregates.

Pure business logic: no SQLAlchemy, no HTTP, no I/O. Persistence is handled by
repositories in `infrastructure/`. All state transitions are guarded by
`DomainError` and emit `DomainEvent`s for the event bus to drain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timezone
from enum import StrEnum
from platform.core.exceptions import DomainError
from platform.domain.shared import (
    AggregateRoot,
    DomainEvent,
    Price,
    Symbol,
    Timeframe,
    ValueObject,
)
from typing import Any
from uuid import UUID

# ── Enums ───────────────────────────────────────────────────────────────────


class SignalSide(StrEnum):
    """Direction a signal advocates trading in."""

    BUY = "buy"
    SELL = "sell"


class SignalStatus(StrEnum):
    """Lifecycle state of a Signal aggregate."""

    PENDING = "pending"
    EVALUATED = "evaluated"
    EXECUTED = "executed"
    EXPIRED = "expired"
    REJECTED = "rejected"


class SignalSource(StrEnum):
    """Where the signal originated."""

    STRATEGY = "strategy"
    AI = "ai"
    MANUAL = "manual"


# ── Value objects ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SignalStrength(ValueObject):
    """Normalised conviction in [0.0, 1.0] — drives position sizing & filtering."""

    value: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.value <= 1.0:
            raise DomainError(f"SignalStrength must be in [0,1], got {self.value}")

    @property
    def is_strong(self) -> bool:
        """Strength ≥ 0.7 — typically eligible for full position size."""
        return self.value >= 0.7

    @property
    def is_weak(self) -> bool:
        """Strength < 0.3 — typically filtered out before reaching execution."""
        return self.value < 0.3


@dataclass(frozen=True)
class StrategyConfig(ValueObject):
    """Versioned strategy parameters with optional per-rule risk overrides.

    Behaves like a dict via `params` while keeping `version` and `risk_overrides`
    as first-class fields so they cannot be silently merged into params.
    """

    version: str
    params: dict[str, Any] = field(default_factory=dict)
    risk_overrides: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.version:
            raise DomainError("StrategyConfig.version is required")

    def get(self, key: str, default: Any = None) -> Any:
        return self.params.get(key, default)

    def with_params(self, **overrides: Any) -> StrategyConfig:
        return StrategyConfig(
            version=self.version,
            params={**self.params, **overrides},
            risk_overrides=self.risk_overrides,
        )


# ── Domain events ───────────────────────────────────────────────────────────


@dataclass(kw_only=True)
class SignalEmitted(DomainEvent):
    signal_id: UUID
    strategy_id: UUID
    symbol: str
    side: str
    strength: float


@dataclass(kw_only=True)
class SignalEvaluated(DomainEvent):
    signal_id: UUID
    passed: bool


@dataclass(kw_only=True)
class SignalExecuted(DomainEvent):
    signal_id: UUID
    order_id: UUID


@dataclass(kw_only=True)
class SignalExpired(DomainEvent):
    signal_id: UUID
    reason: str


@dataclass(kw_only=True)
class SignalRejected(DomainEvent):
    signal_id: UUID
    reason: str


@dataclass(kw_only=True)
class StrategyActivated(DomainEvent):
    strategy_id: UUID
    org_id: UUID


@dataclass(kw_only=True)
class StrategyDeactivated(DomainEvent):
    strategy_id: UUID


@dataclass(kw_only=True)
class StrategyVersionBumped(DomainEvent):
    strategy_id: UUID
    old_version: str
    new_version: str


# ── Signal aggregate ────────────────────────────────────────────────────────


@dataclass(kw_only=True)
class Signal(AggregateRoot):
    """A trading signal emitted by a strategy or AI module.

    Lifecycle: PENDING → (EVALUATED → EXECUTED | REJECTED | EXPIRED).
    State transitions are one-way terminal: once EXECUTED/EXPIRED/REJECTED the
    signal cannot be moved.
    """

    org_id: UUID
    strategy_id: UUID
    terminal_id: UUID
    symbol: Symbol
    side: SignalSide
    strength: SignalStrength
    timeframe: Timeframe
    price: Price
    meta: dict[str, Any] = field(default_factory=dict)
    source: SignalSource = SignalSource.STRATEGY
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    status: SignalStatus = SignalStatus.PENDING
    rejection_reason: str | None = None
    executed_order_id: UUID | None = None

    def __post_init__(self) -> None:
        self.record_event(
            SignalEmitted(
                signal_id=self.id,
                strategy_id=self.strategy_id,
                symbol=self.symbol.name,
                side=self.side.value,
                strength=self.strength.value,
            )
        )

    def mark_evaluated(self, *, passed: bool = True) -> None:
        """Record that risk/strategy gating has reviewed the signal."""
        if self.status != SignalStatus.PENDING:
            raise DomainError(f"Cannot evaluate signal in status {self.status}")
        self.status = SignalStatus.EVALUATED
        self.record_event(SignalEvaluated(signal_id=self.id, passed=passed))
        if not passed:
            self._reject_internal("failed pre-trade evaluation")

    def mark_executed(self, order_id: UUID) -> None:
        """Bind the signal to the order it produced."""
        if self.status not in (SignalStatus.PENDING, SignalStatus.EVALUATED):
            raise DomainError(f"Cannot execute signal in status {self.status}")
        self.status = SignalStatus.EXECUTED
        self.executed_order_id = order_id
        self.record_event(SignalExecuted(signal_id=self.id, order_id=order_id))

    def mark_expired(self, reason: str = "ttl_elapsed") -> None:
        """Mark the signal as stale — e.g. price moved too far from emission."""
        if self.status in (SignalStatus.EXECUTED, SignalStatus.REJECTED):
            raise DomainError(f"Cannot expire signal in status {self.status}")
        self.status = SignalStatus.EXPIRED
        self.record_event(SignalExpired(signal_id=self.id, reason=reason))

    def mark_rejected(self, reason: str) -> None:
        """Reject from PENDING or EVALUATED state."""
        if self.status in (SignalStatus.EXECUTED, SignalStatus.EXPIRED):
            raise DomainError(f"Cannot reject signal in status {self.status}")
        self._reject_internal(reason)

    def _reject_internal(self, reason: str) -> None:
        self.status = SignalStatus.REJECTED
        self.rejection_reason = reason
        self.record_event(SignalRejected(signal_id=self.id, reason=reason))


# ── Strategy aggregate ──────────────────────────────────────────────────────


@dataclass(kw_only=True)
class Strategy(AggregateRoot):
    """A versioned, activatable strategy definition.

    The aggregate owns its lifecycle (active/inactive) and its config version.
    Mutating config does NOT bump the version — `bump_version` is an explicit
    business decision, typically after a backtest validates new behaviour.
    """

    org_id: UUID
    name: str
    slug: str
    kind: str  # ema_cross | rsi_reversion | smc_ob | custom | ...
    version: str = "1.0.0"
    config: StrategyConfig = field(default_factory=lambda: StrategyConfig(version="1.0.0"))
    is_active: bool = False
    description: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    activated_at: datetime | None = None
    deactivated_at: datetime | None = None

    def activate(self) -> None:
        """Move from inactive → active. Idempotent if already active."""
        if self.is_active:
            return
        self.is_active = True
        self.activated_at = datetime.now(UTC)
        self.deactivated_at = None
        self.record_event(StrategyActivated(strategy_id=self.id, org_id=self.org_id))

    def deactivate(self) -> None:
        """Move from active → inactive. Idempotent if already inactive."""
        if not self.is_active:
            return
        self.is_active = False
        self.deactivated_at = datetime.now(UTC)
        self.record_event(StrategyDeactivated(strategy_id=self.id))

    def update_config(self, new_config: StrategyConfig) -> None:
        """Replace the config in place. Does NOT bump `version` — call
        `bump_version` for that."""
        if not isinstance(new_config, StrategyConfig):
            raise DomainError("update_config requires a StrategyConfig")
        self.config = new_config

    def bump_version(self, new_version: str) -> None:
        """Promote to a new semantic version. Triggers StrategyVersionBumped."""
        if new_version == self.version:
            raise DomainError("new_version equals current version")
        old = self.version
        self.version = new_version
        # Keep config.version aligned unless caller supplies a newer one later.
        self.config = StrategyConfig(
            version=new_version,
            params=self.config.params,
            risk_overrides=self.config.risk_overrides,
        )
        self.record_event(
            StrategyVersionBumped(
                strategy_id=self.id,
                old_version=old,
                new_version=new_version,
            )
        )


__all__ = [
    "Signal",
    "SignalEmitted",
    "SignalEvaluated",
    "SignalExecuted",
    "SignalExpired",
    "SignalRejected",
    "SignalSide",
    "SignalSource",
    "SignalStatus",
    "SignalStrength",
    "Strategy",
    "StrategyActivated",
    "StrategyConfig",
    "StrategyDeactivated",
    "StrategyVersionBumped",
]
