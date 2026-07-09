"""Test the Strategy + Signal aggregates — lifecycle transitions, events."""

from __future__ import annotations

from platform.core.exceptions import DomainError
from platform.domain.shared import Price, Symbol, Timeframe
from platform.domain.strategy import (
    Signal,
    SignalSide,
    SignalSource,
    SignalStatus,
    SignalStrength,
    Strategy,
    StrategyConfig,
)
from uuid import uuid4

import pytest


def _make_strategy() -> Strategy:
    """Build a fresh inactive Strategy aggregate."""
    return Strategy(
        org_id=uuid4(),
        name="My EMA Cross",
        slug="my-ema-cross",
        kind="ema_cross",
    )


def _make_signal(strength: float = 0.8) -> Signal:
    """Build a fresh PENDING Signal aggregate."""
    return Signal(
        org_id=uuid4(),
        strategy_id=uuid4(),
        terminal_id=uuid4(),
        symbol=Symbol(name="XAUUSD"),
        side=SignalSide.BUY,
        strength=SignalStrength(value=strength),
        timeframe=Timeframe(code="M15"),
        price=Price(value=2000.0),
    )


# ── SignalStrength value object ──────────────────────────────────────────────


def test_signal_strength_rejects_out_of_range() -> None:
    """SignalStrength must be in [0.0, 1.0]."""
    with pytest.raises(DomainError):
        SignalStrength(value=1.5)
    with pytest.raises(DomainError):
        SignalStrength(value=-0.1)


def test_signal_strength_classifies_strong_and_weak() -> None:
    """is_strong / is_weak use 0.7 / 0.3 thresholds."""
    assert SignalStrength(value=0.75).is_strong
    assert not SignalStrength(value=0.5).is_strong
    assert SignalStrength(value=0.2).is_weak
    assert not SignalStrength(value=0.5).is_weak


# ── StrategyConfig value object ──────────────────────────────────────────────


def test_strategy_config_requires_version() -> None:
    """StrategyConfig rejects an empty version."""
    with pytest.raises(DomainError):
        StrategyConfig(version="")


def test_strategy_config_with_params_returns_new_instance() -> None:
    """with_params is immutable — returns a new config with overrides merged."""
    cfg = StrategyConfig(version="1.0.0", params={"fast": 9})
    cfg2 = cfg.with_params(fast=12, slow=21)
    assert cfg.get("fast") == 9  # original unchanged
    assert cfg2.get("fast") == 12
    assert cfg2.get("slow") == 21


# ── Strategy aggregate lifecycle ─────────────────────────────────────────────


def test_strategy_starts_inactive() -> None:
    """New strategies default to is_active=False."""
    strat = _make_strategy()
    assert strat.is_active is False
    assert strat.activated_at is None


def test_strategy_activate_sets_flag_and_timestamp() -> None:
    """activate() flips is_active and stamps activated_at."""
    strat = _make_strategy()
    strat.activate()
    assert strat.is_active is True
    assert strat.activated_at is not None
    assert strat.deactivated_at is None


def test_strategy_activate_is_idempotent() -> None:
    """Activating an already-active strategy is a no-op."""
    strat = _make_strategy()
    strat.activate()
    first_at = strat.activated_at
    strat.activate()  # second call should not raise or reset timestamp
    assert strat.activated_at == first_at


def test_strategy_deactivate_clears_active_flag() -> None:
    """deactivate() flips is_active back to False."""
    strat = _make_strategy()
    strat.activate()
    strat.deactivate()
    assert strat.is_active is False
    assert strat.deactivated_at is not None


def test_strategy_bump_version_replaces_config_version() -> None:
    """bump_version aligns the embedded config.version."""
    strat = _make_strategy()
    strat.bump_version("2.0.0")
    assert strat.version == "2.0.0"
    assert strat.config.version == "2.0.0"


def test_strategy_bump_version_rejects_same_version() -> None:
    """bump_version to the current version raises DomainError."""
    strat = _make_strategy()
    with pytest.raises(DomainError):
        strat.bump_version(strat.version)


def test_strategy_update_config_replaces_config_in_place() -> None:
    """update_config swaps the config object; version unchanged."""
    strat = _make_strategy()
    original_version = strat.version
    new_cfg = StrategyConfig(version="1.0.0", params={"period": 14})
    strat.update_config(new_cfg)
    assert strat.config is new_cfg
    assert strat.version == original_version


# ── Signal aggregate lifecycle ───────────────────────────────────────────────


def test_signal_starts_pending_with_emitted_event() -> None:
    """A new Signal is PENDING and emits SignalEmitted on construction."""
    sig = _make_signal()
    assert sig.status == SignalStatus.PENDING
    events = sig.collect_events()
    assert len(events) == 1
    assert events[0].__class__.__name__ == "SignalEmitted"


def test_signal_mark_evaluated_transitions_to_evaluated() -> None:
    """mark_evaluated passes the signal through the risk gate."""
    sig = _make_signal()
    sig.mark_evaluated(passed=True)
    assert sig.status == SignalStatus.EVALUATED


def test_signal_mark_evaluated_failed_rejects() -> None:
    """mark_evaluated(passed=False) cascades into REJECTED."""
    sig = _make_signal()
    sig.mark_evaluated(passed=False)
    assert sig.status == SignalStatus.REJECTED
    assert sig.rejection_reason is not None


def test_signal_mark_executed_binds_order_id() -> None:
    """mark_executed sets the executed_order_id and transitions to EXECUTED."""
    sig = _make_signal()
    sig.mark_evaluated(passed=True)
    order_id = uuid4()
    sig.mark_executed(order_id)
    assert sig.status == SignalStatus.EXECUTED
    assert sig.executed_order_id == order_id


def test_signal_mark_executed_from_pending_works_too() -> None:
    """Pending signals can also be marked executed directly."""
    sig = _make_signal()
    sig.mark_executed(uuid4())
    assert sig.status == SignalStatus.EXECUTED


def test_signal_cannot_execute_rejected() -> None:
    """A REJECTED signal cannot be moved to EXECUTED."""
    sig = _make_signal()
    sig.mark_rejected("manual")
    with pytest.raises(DomainError):
        sig.mark_executed(uuid4())


def test_signal_mark_expired_transitions_state() -> None:
    """mark_expired moves PENDING/EVALUATED to EXPIRED."""
    sig = _make_signal()
    sig.mark_expired(reason="ttl_elapsed")
    assert sig.status == SignalStatus.EXPIRED


def test_signal_cannot_expire_executed() -> None:
    """An EXECUTED signal cannot be expired."""
    sig = _make_signal()
    sig.mark_executed(uuid4())
    with pytest.raises(DomainError):
        sig.mark_expired()


def test_signal_manual_source_round_trip() -> None:
    """Signal.source can be set to MANUAL at construction."""
    sig = Signal(
        org_id=uuid4(),
        strategy_id=uuid4(),
        terminal_id=uuid4(),
        symbol=Symbol(name="EURUSD"),
        side=SignalSide.SELL,
        strength=SignalStrength(value=0.6),
        timeframe=Timeframe(code="M5"),
        price=Price(value=1.0850),
        source=SignalSource.MANUAL,
    )
    assert sig.source == SignalSource.MANUAL
