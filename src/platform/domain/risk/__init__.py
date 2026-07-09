"""Risk bounded context — RiskEvent aggregate + RiskState value object.

Models per-org runtime risk state and the audit trail of breaches. Pure Python
domain layer; the evaluation engine that produces RiskEvents lives in
`platform/services/risk_engine/`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timezone
from enum import StrEnum
from platform.core.exceptions import DomainError
from platform.domain.shared import AggregateRoot, DomainEvent, ValueObject
from typing import Any
from uuid import UUID

# ── Enums ───────────────────────────────────────────────────────────────────


class RiskSeverity(StrEnum):
    """How serious a breach is — drives notification routing & response."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    KILL = "kill"


class RiskAction(StrEnum):
    """What the risk engine did in response to a breach."""

    LOG = "log"
    BLOCK = "block"
    CLOSE_ALL = "close_all"
    DISABLE = "disable"
    NOTIFY = "notify"


class RiskRuleName(StrEnum):
    """Canonical names for the 12 risk rules in the platform."""

    KILL_SWITCH = "kill_switch"
    MAX_DAILY_LOSS = "max_daily_loss"
    MAX_WEEKLY_LOSS = "max_weekly_loss"
    MAX_DRAWDOWN = "max_drawdown"
    POSITION_LIMIT = "position_limit"
    MAX_EXPOSURE = "max_exposure"
    CORRELATION_RISK = "correlation_risk"
    SECTOR_EXPOSURE = "sector_exposure"
    SPREAD_PROTECTION = "spread_protection"
    NEWS_LOCK = "news_lock"
    VOLATILITY_LOCK = "volatility_lock"
    KELLY_SIZING = "kelly_sizing"


# ── Value objects ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RiskThreshold(ValueObject):
    """A snapshot of a rule's limit, the current reading, and breach math.

    `breach_ratio = |current| / |limit|` is direction-agnostic so it works for
    loss limits (current < 0, limit < 0), exposure limits (both positive), and
    count limits (both positive integers). `is_breached` is True at ratio ≥ 1.
    """

    rule_name: RiskRuleName
    limit_value: float
    current_value: float

    def __post_init__(self) -> None:
        if self.limit_value == 0:
            raise DomainError("limit_value cannot be zero")

    @property
    def breach_ratio(self) -> float:
        return abs(self.current_value) / abs(self.limit_value)

    @property
    def is_breached(self) -> bool:
        return self.breach_ratio >= 1.0

    @property
    def is_warning(self) -> bool:
        """80–100% of limit — pre-breach early warning band."""
        return 0.8 <= self.breach_ratio < 1.0


@dataclass(frozen=True)
class RiskState(ValueObject):
    """Immutable per-org runtime risk state.

    All mutators return a new RiskState (value-object semantics). The risk
    engine holds the current instance and folds each market update through
    `with_daily_pnl` / `with_new_position` to produce the next state.
    """

    org_id: UUID
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    current_drawdown: float = 0.0
    open_exposure: float = 0.0
    kill_switch_engaged: bool = False
    positions_count: int = 0

    def with_daily_pnl(self, delta: float) -> RiskState:
        """Apply a realised-PnL delta (positive for profit, negative for loss)."""
        return replace(
            self,
            daily_pnl=self.daily_pnl + delta,
            weekly_pnl=self.weekly_pnl + delta,
            current_drawdown=min(self.current_drawdown, self.daily_pnl + delta),
        )

    def with_new_position(self, exposure_value: float) -> RiskState:
        """Record a new position opened with the given notional exposure."""
        if exposure_value < 0:
            raise DomainError("exposure_value must be non-negative")
        return replace(
            self,
            open_exposure=self.open_exposure + exposure_value,
            positions_count=self.positions_count + 1,
        )

    def with_closed_position(self, exposure_value: float) -> RiskState:
        """Mirror of `with_new_position` for position close."""
        return replace(
            self,
            open_exposure=max(0.0, self.open_exposure - exposure_value),
            positions_count=max(0, self.positions_count - 1),
        )

    def engage_kill_switch(self) -> RiskState:
        return replace(self, kill_switch_engaged=True)

    def release_kill_switch(self) -> RiskState:
        return replace(self, kill_switch_engaged=False)

    def check_breach(self, threshold: RiskThreshold) -> bool:
        """Pure delegation to the threshold — kept here for ergonomics."""
        if threshold.rule_name == RiskRuleName.MAX_DAILY_LOSS:
            return self.daily_pnl <= threshold.limit_value
        if threshold.rule_name == RiskRuleName.MAX_WEEKLY_LOSS:
            return self.weekly_pnl <= threshold.limit_value
        if threshold.rule_name == RiskRuleName.MAX_DRAWDOWN:
            return self.current_drawdown <= threshold.limit_value
        if threshold.rule_name == RiskRuleName.POSITION_LIMIT:
            return self.positions_count >= int(threshold.limit_value)
        if threshold.rule_name == RiskRuleName.MAX_EXPOSURE:
            return self.open_exposure >= threshold.limit_value
        if threshold.rule_name == RiskRuleName.KILL_SWITCH:
            return self.kill_switch_engaged
        return threshold.is_breached


# ── Domain events ───────────────────────────────────────────────────────────


@dataclass(kw_only=True)
class RiskLimitBreached(DomainEvent):
    risk_event_id: UUID
    org_id: UUID
    rule: str
    severity: str
    action: str
    details: dict[str, Any]


@dataclass(kw_only=True)
class RiskResolved(DomainEvent):
    risk_event_id: UUID
    resolution: str


@dataclass(kw_only=True)
class RiskEscalated(DomainEvent):
    risk_event_id: UUID
    from_severity: str
    to_severity: str


# ── RiskEvent aggregate ─────────────────────────────────────────────────────


@dataclass(kw_only=True)
class RiskEvent(AggregateRoot):
    """A persisted risk-rule breach with resolution lifecycle.

    States are implicit: unresolved (resolved_at is None) → resolved.
    Severity can only escalate, never de-escalate — prevents hiding a critical
    event by re-tagging it as a warning.
    """

    org_id: UUID
    terminal_id: UUID | None
    rule: RiskRuleName
    severity: RiskSeverity = RiskSeverity.WARNING
    action: RiskAction = RiskAction.LOG
    details: dict[str, Any] = field(default_factory=dict)
    order_id: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None
    resolution: str | None = None

    _severity_rank: dict[str, int] = field(
        default_factory=lambda: {s.value: i for i, s in enumerate(RiskSeverity)},
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        self.record_event(
            RiskLimitBreached(
                risk_event_id=self.id,
                org_id=self.org_id,
                rule=self.rule.value,
                severity=self.severity.value,
                action=self.action.value,
                details=self.details,
            )
        )

    def resolve(self, notes: str) -> None:
        """Mark the breach resolved with operator notes. Idempotency: errors
        if already resolved."""
        if self.resolved_at is not None:
            raise DomainError("RiskEvent already resolved")
        if not notes.strip():
            raise DomainError("resolution notes required")
        self.resolved_at = datetime.now(UTC)
        self.resolution = notes.strip()
        self.record_event(RiskResolved(risk_event_id=self.id, resolution=notes.strip()))

    def escalate(self, to: RiskSeverity) -> None:
        """Raise severity — only upward in the INFO→WARNING→CRITICAL→KILL order."""
        if self.resolved_at is not None:
            raise DomainError("Cannot escalate resolved RiskEvent")
        if self._severity_rank[to.value] <= self._severity_rank[self.severity.value]:
            raise DomainError(f"Cannot escalate {self.severity.value} → {to.value} (not upward)")
        from_severity = self.severity
        self.severity = to
        # Side-effect: CLOSE_ALL kicks in once we reach CRITICAL or KILL.
        if to in (RiskSeverity.CRITICAL, RiskSeverity.KILL):
            self.action = RiskAction.CLOSE_ALL
        self.record_event(
            RiskEscalated(
                risk_event_id=self.id,
                from_severity=from_severity.value,
                to_severity=to.value,
            )
        )


__all__ = [
    "RiskAction",
    "RiskEscalated",
    "RiskEvent",
    "RiskLimitBreached",
    "RiskResolved",
    "RiskRuleName",
    "RiskSeverity",
    "RiskState",
    "RiskThreshold",
]
