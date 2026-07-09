"""Risk rule pack — the catalogue of pluggable risk rules.

Each module here defines a single :class:`~platform.risk.engine.RiskRule`
subclass. Importing from this package gives you the full set of rules
in one place, plus :func:`register_all_rules` to wire them into a
:class:`~platform.risk.engine.RiskEngine` in a single call.

Adding a new rule:
    1. Create ``my_rule.py`` in this package with a ``MyRule(RiskRule)`` class.
    2. Re-export it here.
    3. Append it to ``register_all_rules``.
"""

from __future__ import annotations

from platform.risk.engine import RiskEngine, RiskRule
from platform.risk.rules.correlation_risk import CorrelationRiskRule
from platform.risk.rules.kelly_sizing import KellySizingRule
from platform.risk.rules.max_exposure import MaxExposureRule
from platform.risk.rules.news_lock import NewsLockRule
from platform.risk.rules.position_limit import PositionLimitRule
from platform.risk.rules.sector_exposure import SectorExposureRule
from platform.risk.rules.spread_protection import SpreadProtectionRule
from platform.risk.rules.volatility_lock import VolatilityLockRule

__all__ = [
    "ALL_RULES",
    "CorrelationRiskRule",
    "KellySizingRule",
    "MaxExposureRule",
    "NewsLockRule",
    "PositionLimitRule",
    "RiskRule",
    "SectorExposureRule",
    "SpreadProtectionRule",
    "VolatilityLockRule",
    "register_all_rules",
]


# Ordered list — order matters: cheapest checks first.
ALL_RULES: list[type[RiskRule]] = [
    PositionLimitRule,
    MaxExposureRule,
    SectorExposureRule,
    CorrelationRiskRule,
    SpreadProtectionRule,
    NewsLockRule,
    VolatilityLockRule,
    KellySizingRule,
]


def register_all_rules(engine: RiskEngine) -> None:
    """Register every rule in :data:`ALL_RULES` onto ``engine``.

    The :class:`~platform.risk.engine.RiskEngine` already registers the
    kill-switch, daily-loss, and drawdown rules in its constructor, so
    this function only adds the rules in this pack.

    Parameters
    ----------
    engine:
        The risk engine instance to wire up.
    """
    for rule_cls in ALL_RULES:
        engine.register(rule_cls())
