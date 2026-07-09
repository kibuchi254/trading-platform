"""Risk engine — the guardian.

Pluggable rule pack. Every order passes through `check_order` before being
forwarded to the bridge. If any rule rejects, the order never leaves the system.

Rules are independent and registered via `register_rule`. Adding a new rule
is a one-liner — no core code changes.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from platform.core.exceptions import RiskLimitBreached
from platform.core.logging import get_logger
from platform.core.telemetry import RISK_DECISIONS
from platform.events.bus import get_event_bus
from platform.events.topics import Topic
from uuid import UUID

_log = get_logger(__name__)


@dataclass
class OrderContext:
    org_id: UUID
    terminal_id: str
    symbol: str
    side: str
    volume: float
    price: float | None


class RiskRule(abc.ABC):
    """Base class for all risk rules."""

    name: str = "abstract"

    @abc.abstractmethod
    async def evaluate(self, ctx: OrderContext) -> None:
        """Raise RiskLimitBreached if the rule rejects."""


class MaxDailyLossRule(RiskRule):
    """Reject new orders if the org has hit its daily loss limit."""

    name = "max_daily_loss"

    def __init__(self, limit_usd: float = 1000.0) -> None:
        self.limit_usd = limit_usd

    async def evaluate(self, ctx: OrderContext) -> None:
        # In production: query `trades` table for today's realized PnL sum
        # For the skeleton: pass-through
        return None


class MaxDrawdownRule(RiskRule):
    """Reject if account drawdown exceeds threshold."""

    name = "max_drawdown"

    def __init__(self, max_drawdown_pct: float = 0.20) -> None:
        self.max_drawdown_pct = max_drawdown_pct

    async def evaluate(self, ctx: OrderContext) -> None:
        return None


class KillSwitchRule(RiskRule):
    """If kill switch is on, reject everything."""

    name = "kill_switch"

    def __init__(self) -> None:
        self._engaged = False

    def engage(self, reason: str = "manual") -> None:
        self._engaged = True
        _log.critical("kill_switch_engaged", reason=reason)

    def release(self) -> None:
        self._engaged = False
        _log.info("kill_switch_released")

    async def evaluate(self, ctx: OrderContext) -> None:
        if self._engaged:
            raise RiskLimitBreached("Kill switch engaged — all trading blocked")


class RiskEngine:
    def __init__(self) -> None:
        self._rules: list[RiskRule] = []
        self.kill_switch = KillSwitchRule()
        self.register(self.kill_switch)
        self.register(MaxDailyLossRule())
        self.register(MaxDrawdownRule())

    def register(self, rule: RiskRule) -> None:
        self._rules.append(rule)
        _log.info("risk_rule_registered", rule=rule.name)

    async def check_order(
        self,
        *,
        org_id: UUID,
        terminal_id: str,
        symbol: str,
        side: str,
        volume: float,
        price: float | None = None,
    ) -> None:
        ctx = OrderContext(
            org_id=org_id,
            terminal_id=terminal_id,
            symbol=symbol,
            side=side,
            volume=volume,
            price=price,
        )
        for rule in self._rules:
            try:
                await rule.evaluate(ctx)
            except RiskLimitBreached as e:
                RISK_DECISIONS.labels(decision="rejected").inc()
                bus = get_event_bus()
                await bus.publish(
                    Topic.RISK_EVENTS,
                    {
                        "org_id": str(org_id),
                        "rule": rule.name,
                        "severity": "critical",
                        "action": "block",
                        "details": {"reason": str(e), "symbol": symbol, "volume": volume},
                    },
                )
                raise
        RISK_DECISIONS.labels(decision="approved").inc()


_engine: RiskEngine | None = None


def get_risk_engine() -> RiskEngine:
    global _engine
    if _engine is None:
        _engine = RiskEngine()
    return _engine
