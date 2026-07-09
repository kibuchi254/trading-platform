"""Test the risk domain — RiskEvent, RiskThreshold, RiskState value objects."""

from __future__ import annotations

from platform.core.exceptions import DomainError
from platform.domain.risk import (
    RiskAction,
    RiskEvent,
    RiskRuleName,
    RiskSeverity,
    RiskState,
    RiskThreshold,
)
from uuid import uuid4

import pytest

# ── RiskThreshold value object ───────────────────────────────────────────────


def test_threshold_breach_ratio_uses_absolute_values() -> None:
    """breach_ratio is direction-agnostic (|current|/|limit|)."""
    t = RiskThreshold(
        rule_name=RiskRuleName.MAX_DAILY_LOSS,
        limit_value=-1000.0,
        current_value=-800.0,
    )
    assert t.breach_ratio == pytest.approx(0.8)


def test_threshold_is_breached_at_ratio_one_or_more() -> None:
    """is_breached fires at exactly 100% of limit."""
    breached = RiskThreshold(
        rule_name=RiskRuleName.MAX_DAILY_LOSS,
        limit_value=-1000.0,
        current_value=-1000.0,
    )
    assert breached.is_breached
    over = RiskThreshold(
        rule_name=RiskRuleName.MAX_DAILY_LOSS,
        limit_value=-1000.0,
        current_value=-1200.0,
    )
    assert over.is_breached


def test_threshold_is_warning_in_80_to_100_pct_band() -> None:
    """The 80–100% band is the pre-breach early-warning zone."""
    warn = RiskThreshold(
        rule_name=RiskRuleName.MAX_DAILY_LOSS,
        limit_value=-1000.0,
        current_value=-850.0,
    )
    assert warn.is_warning
    assert not warn.is_breached


def test_threshold_rejects_zero_limit() -> None:
    """A zero limit_value is invalid (division-by-zero protection)."""
    with pytest.raises(DomainError):
        RiskThreshold(
            rule_name=RiskRuleName.MAX_DAILY_LOSS,
            limit_value=0.0,
            current_value=0.0,
        )


# ── RiskState value object ───────────────────────────────────────────────────


def test_risk_state_with_daily_pnl_returns_new_instance() -> None:
    """Mutators are immutable — they return a new RiskState."""
    s0 = RiskState(org_id=uuid4())
    s1 = s0.with_daily_pnl(-100.0)
    assert s0.daily_pnl == 0.0
    assert s1.daily_pnl == -100.0
    assert s1.weekly_pnl == -100.0


def test_risk_state_with_new_position_increments_count_and_exposure() -> None:
    """with_new_position adds to both open_exposure and positions_count."""
    s0 = RiskState(org_id=uuid4())
    s1 = s0.with_new_position(5000.0)
    assert s1.open_exposure == 5000.0
    assert s1.positions_count == 1


def test_risk_state_with_new_position_rejects_negative_exposure() -> None:
    """Negative exposure is not a valid input — we cannot short the notional."""
    s0 = RiskState(org_id=uuid4())
    with pytest.raises(DomainError):
        s0.with_new_position(-100.0)


def test_risk_state_with_closed_position_clamps_at_zero() -> None:
    """Closing more than exists does not produce negative exposure."""
    s0 = RiskState(org_id=uuid4()).with_new_position(1000.0)
    s1 = s0.with_closed_position(1500.0)
    assert s1.open_exposure == 0.0
    assert s1.positions_count == 0


def test_risk_state_engage_and_release_kill_switch() -> None:
    """Kill-switch flag toggles via engage/release."""
    s0 = RiskState(org_id=uuid4())
    assert s0.kill_switch_engaged is False
    s1 = s0.engage_kill_switch()
    assert s1.kill_switch_engaged is True
    s2 = s1.release_kill_switch()
    assert s2.kill_switch_engaged is False


def test_risk_state_check_breach_max_daily_loss() -> None:
    """check_breach for MAX_DAILY_LOSS uses <= comparison."""
    org = uuid4()
    s = RiskState(org_id=org, daily_pnl=-1500.0)
    threshold = RiskThreshold(
        rule_name=RiskRuleName.MAX_DAILY_LOSS,
        limit_value=-1000.0,
        current_value=-1500.0,
    )
    assert s.check_breach(threshold) is True


def test_risk_state_check_breach_position_limit() -> None:
    """check_breach for POSITION_LIMIT triggers when count >= limit."""
    s = RiskState(org_id=uuid4(), positions_count=10)
    threshold = RiskThreshold(
        rule_name=RiskRuleName.POSITION_LIMIT,
        limit_value=10,
        current_value=10,
    )
    assert s.check_breach(threshold) is True


def test_risk_state_check_breach_kill_switch() -> None:
    """check_breach for KILL_SWITCH returns the flag directly."""
    s = RiskState(org_id=uuid4()).engage_kill_switch()
    threshold = RiskThreshold(
        rule_name=RiskRuleName.KILL_SWITCH,
        limit_value=1,
        current_value=1,
    )
    assert s.check_breach(threshold) is True


# ── RiskEvent aggregate ──────────────────────────────────────────────────────


def _make_event(severity: RiskSeverity = RiskSeverity.WARNING) -> RiskEvent:
    return RiskEvent(
        org_id=uuid4(),
        terminal_id="t1",
        rule=RiskRuleName.MAX_DAILY_LOSS,
        severity=severity,
        action=RiskAction.LOG,
        details={"loss": -1500.0},
    )


def test_risk_event_starts_unresolved_and_emits_breached_event() -> None:
    """A fresh RiskEvent has resolved_at=None and emits RiskLimitBreached."""
    ev = _make_event()
    assert ev.resolved_at is None
    events = ev.collect_events()
    assert len(events) == 1
    assert events[0].__class__.__name__ == "RiskLimitBreached"


def test_risk_event_resolve_records_notes_and_timestamp() -> None:
    """resolve() stamps resolved_at and stores notes."""
    ev = _make_event()
    ev.resolve("Operator confirmed false positive")
    assert ev.resolved_at is not None
    assert ev.resolution == "Operator confirmed false positive"


def test_risk_event_resolve_rejects_empty_notes() -> None:
    """An empty resolution is rejected — operators must explain."""
    ev = _make_event()
    with pytest.raises(DomainError):
        ev.resolve("   ")


def test_risk_event_resolve_is_not_idempotent() -> None:
    """Double-resolve raises DomainError."""
    ev = _make_event()
    ev.resolve("first resolution")
    with pytest.raises(DomainError):
        ev.resolve("second resolution")


def test_risk_event_escalate_raises_severity_and_upgrades_action() -> None:
    """Escalating to CRITICAL upgrades the action to CLOSE_ALL."""
    ev = _make_event(RiskSeverity.WARNING)
    ev.escalate(RiskSeverity.CRITICAL)
    assert ev.severity == RiskSeverity.CRITICAL
    assert ev.action == RiskAction.CLOSE_ALL


def test_risk_event_escalate_rejects_downgrade() -> None:
    """Cannot de-escalate — CRITICAL → WARNING must raise."""
    ev = _make_event(RiskSeverity.CRITICAL)
    with pytest.raises(DomainError):
        ev.escalate(RiskSeverity.WARNING)


def test_risk_event_escalate_rejects_same_level() -> None:
    """Escalating to the same level is not an escalation."""
    ev = _make_event(RiskSeverity.WARNING)
    with pytest.raises(DomainError):
        ev.escalate(RiskSeverity.WARNING)


def test_risk_event_cannot_escalate_after_resolution() -> None:
    """A resolved event is frozen — no further escalation."""
    ev = _make_event()
    ev.resolve("done")
    with pytest.raises(DomainError):
        ev.escalate(RiskSeverity.CRITICAL)
