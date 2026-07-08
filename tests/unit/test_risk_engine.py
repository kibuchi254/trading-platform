"""Test the risk engine — verify rule registration + kill switch behavior."""
from __future__ import annotations

import pytest
from uuid import uuid4

from platform.core.exceptions import RiskLimitBreached
from platform.events.bus import EventBus
from platform.risk.engine import RiskEngine, KillSwitchRule


async def test_engine_approves_when_no_rule_blocks(monkeypatch) -> None:
    # Force local-only bus (no Redis) for test
    import platform.events.bus as bus_mod
    monkeypatch.setattr(bus_mod, "get_event_bus", lambda: EventBus())
    from platform.risk import engine as eng_mod
    monkeypatch.setattr(eng_mod, "get_event_bus", lambda: EventBus())

    eng = RiskEngine()
    await eng.check_order(
        org_id=uuid4(), terminal_id="t1", symbol="XAUUSD",
        side="buy", volume=0.10, price=2000.0,
    )  # should not raise


async def test_kill_switch_blocks_all_orders(monkeypatch) -> None:
    import platform.events.bus as bus_mod
    monkeypatch.setattr(bus_mod, "get_event_bus", lambda: EventBus())
    from platform.risk import engine as eng_mod
    monkeypatch.setattr(eng_mod, "get_event_bus", lambda: EventBus())

    eng = RiskEngine()
    eng.kill_switch.engage(reason="test")
    with pytest.raises(RiskLimitBreached):
        await eng.check_order(
            org_id=uuid4(), terminal_id="t1", symbol="XAUUSD",
            side="buy", volume=0.10, price=2000.0,
        )
    eng.kill_switch.release()
