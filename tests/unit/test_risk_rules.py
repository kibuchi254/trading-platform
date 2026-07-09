"""Test the 8 risk rules in the platform.risk.rules pack.

Each test constructs a `RiskRule` instance, drives its evaluate() method
with a mock OrderContext, and verifies the rule approves or rejects as
expected. Database access is monkeypatched per-test via a fake
async-context-manager so the rules can be exercised without a live
PostgreSQL instance.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC
from platform.core.exceptions import RiskLimitBreached
from platform.risk.engine import OrderContext
from uuid import uuid4

import pytest


def _ctx(**overrides) -> OrderContext:
    """Build an OrderContext with sensible defaults for tests."""
    defaults = dict(
        org_id=uuid4(),
        terminal_id="t1",
        symbol="XAUUSD",
        side="buy",
        volume=0.10,
        price=2000.0,
    )
    defaults.update(overrides)
    return OrderContext(**defaults)


def _fake_session_factory(
    *,
    total_open: int = 0,
    sym_open: int = 0,
    rows=None,
    contract_size: float = 1.0,
    open_symbols: list[str] | None = None,
    candle_closes_by_sym: dict[str, list[float]] | None = None,
    pnls: list[float] | None = None,
):
    """Build a fake async-context-manager that yields a mock AsyncSession.

    The session's `execute()` returns a result object whose helpers
    (scalar_one / scalar_one_or_none / all / scalars().all()) follow the
    behaviour expected by the rules under test.
    """
    state = {
        "call": 0,  # tracks which query we're on
    }

    class _Result:
        def __init__(self, call_idx: int):
            self._call_idx = call_idx

        def scalar_one(self):
            # PositionLimitRule: 1st call=total, 2nd=sym.
            if state["call"] == 1:
                return total_open
            return sym_open

        def scalar_one_or_none(self):
            return contract_size  # MaxExposureRule contract_size lookup

        def all(self):
            if rows is not None:
                return rows
            return []

        def scalars(self):
            class _S:
                def all(self_inner):
                    # CorrelationRiskRule: 1st call returns open_symbols,
                    # subsequent calls return candle closes.
                    if open_symbols is not None and state["call"] == 1:
                        return open_symbols
                    # KellySizingRule: returns pnls.
                    if pnls is not None:
                        return pnls
                    # CorrelationRiskRule candle lookup.
                    if candle_closes_by_sym:
                        # We don't know which symbol here; tests override
                        # _load_closes directly when they need per-symbol data.
                        return list(next(iter(candle_closes_by_sym.values())))
                    return []

            return _S()

    class FakeSession:
        async def execute(self, stmt):
            state["call"] += 1
            return _Result(state["call"])

    @asynccontextmanager
    async def fake_db():
        yield FakeSession()

    return fake_db


# ── PositionLimitRule ────────────────────────────────────────────────────────


async def test_position_limit_allows_below_cap(monkeypatch) -> None:
    """Below both per-symbol and total caps → no rejection."""
    from platform.risk.rules.position_limit import PositionLimitRule

    fake_db = _fake_session_factory(total_open=0, sym_open=0)
    monkeypatch.setattr("platform.risk.rules.position_limit.db_context", fake_db)
    rule = PositionLimitRule(max_positions_per_symbol=5, max_positions_total=50)
    await rule.evaluate(_ctx())  # should not raise


async def test_position_limit_blocks_when_per_symbol_cap_hit(monkeypatch) -> None:
    """Hitting the per-symbol cap raises RiskLimitBreached."""
    from platform.risk.rules.position_limit import PositionLimitRule

    fake_db = _fake_session_factory(sym_open=5)
    monkeypatch.setattr("platform.risk.rules.position_limit.db_context", fake_db)
    rule = PositionLimitRule(max_positions_per_symbol=5, max_positions_total=50)
    with pytest.raises(RiskLimitBreached):
        await rule.evaluate(_ctx())


async def test_position_limit_blocks_when_total_cap_hit(monkeypatch) -> None:
    """Hitting the total positions cap raises RiskLimitBreached."""
    from platform.risk.rules.position_limit import PositionLimitRule

    fake_db = _fake_session_factory(total_open=50, sym_open=0)
    monkeypatch.setattr("platform.risk.rules.position_limit.db_context", fake_db)
    rule = PositionLimitRule(max_positions_per_symbol=5, max_positions_total=50)
    with pytest.raises(RiskLimitBreached):
        await rule.evaluate(_ctx())


# ── MaxExposureRule ──────────────────────────────────────────────────────────


async def test_max_exposure_allows_under_cap(monkeypatch) -> None:
    """Below both per-symbol and total notional caps → no rejection."""
    from platform.risk.rules.max_exposure import MaxExposureRule

    fake_db = _fake_session_factory(rows=[])
    monkeypatch.setattr("platform.risk.rules.max_exposure.db_context", fake_db)
    rule = MaxExposureRule(max_notional_usd=100_000.0, max_notional_per_symbol=25_000.0)
    # 0.10 * 2000 = 200 USD notional — well under both caps.
    await rule.evaluate(_ctx(volume=0.10, price=2000.0))


async def test_max_exposure_blocks_when_per_symbol_cap_exceeded(monkeypatch) -> None:
    """Exceeding per-symbol notional cap raises RiskLimitBreached."""
    from platform.risk.rules.max_exposure import MaxExposureRule

    fake_db = _fake_session_factory(rows=[])
    monkeypatch.setattr("platform.risk.rules.max_exposure.db_context", fake_db)
    rule = MaxExposureRule(max_notional_usd=100_000.0, max_notional_per_symbol=1_000.0)
    # 0.10 * 20000 * 1.0 = 2000 → exceeds 1000 cap
    with pytest.raises(RiskLimitBreached):
        await rule.evaluate(_ctx(volume=0.10, price=20_000.0))


async def test_max_exposure_blocks_when_total_cap_exceeded(monkeypatch) -> None:
    """Exceeding total notional cap raises RiskLimitBreached."""
    from platform.risk.rules.max_exposure import MaxExposureRule

    # Existing positions: 80_000 USD notional on EURUSD.
    rows = [("EURUSD", 0.40, 200_000.0)]
    fake_db = _fake_session_factory(rows=rows)
    monkeypatch.setattr("platform.risk.rules.max_exposure.db_context", fake_db)
    rule = MaxExposureRule(max_notional_usd=100_000.0, max_notional_per_symbol=50_000.0)
    # New order: 0.05 * 50000 * 1.0 = 2500 → total = 80000 + 2500 = 82500 (under cap)
    # Per-symbol EURUSD: 80000 + 0 = 80000 (existing) — but new order is on XAUUSD.
    # XAUUSD per-symbol: 0 + 2500 = 2500 (under cap).
    # Total = 82500 (under cap). So this shouldn't raise. Let me push it over.
    rule = MaxExposureRule(max_notional_usd=80_000.0, max_notional_per_symbol=50_000.0)
    with pytest.raises(RiskLimitBreached):
        await rule.evaluate(_ctx(volume=0.05, price=50_000.0))


# ── SectorExposureRule ───────────────────────────────────────────────────────


async def test_sector_exposure_allows_balanced_book(monkeypatch) -> None:
    """A diversified book stays below the sector cap."""
    from platform.risk.rules.sector_exposure import SectorExposureRule

    # Balanced book: FX, metals, indices, energy each ~equal notional.
    rows = [
        ("EURUSD", 1.0, 1.0),  # fx: 1.0
        ("XAUUSD", 0.001, 1000.0),  # metals: 1.0
        ("US30", 0.001, 1000.0),  # indices: 1.0
        ("XTIUSD", 1.0, 1.0),  # energy: 1.0
    ]
    fake_db = _fake_session_factory(rows=rows)
    monkeypatch.setattr("platform.risk.rules.sector_exposure.db_context", fake_db)
    rule = SectorExposureRule(max_sector_pct=0.50)
    # New XAUUSD order at 0.001 * 1000 = 1.0 notional.
    # metals new total = 2.0, grand total = 5.0, share = 40% < 50%.
    await rule.evaluate(_ctx(volume=0.001, price=1000.0))


async def test_sector_exposure_blocks_concentration(monkeypatch) -> None:
    """Adding more to an already-dominant sector raises RiskLimitBreached."""
    from platform.risk.rules.sector_exposure import SectorExposureRule

    rows = [("XAUUSD", 1.0, 2000.0)]  # all metals, 2000 USD
    fake_db = _fake_session_factory(rows=rows)
    monkeypatch.setattr("platform.risk.rules.sector_exposure.db_context", fake_db)
    rule = SectorExposureRule(max_sector_pct=0.50)
    # New metals: 200 + 2000 = 2200; share = 100% > 50%.
    with pytest.raises(RiskLimitBreached):
        await rule.evaluate(_ctx(volume=0.10, price=2000.0))


def test_sector_exposure_symbol_to_sector_mapping() -> None:
    """The default sector map classifies well-known symbols."""
    from platform.risk.rules.sector_exposure import SectorExposureRule

    rule = SectorExposureRule()
    assert rule._sector_of("XAUUSD") == "metals"
    assert rule._sector_of("EURUSD") == "fx"
    assert rule._sector_of("BTCUSD") == "crypto"
    assert rule._sector_of("US30") == "indices"
    assert rule._sector_of("XTIUSD") == "energy"
    assert rule._sector_of("FOOBAR") == "other"


# ── CorrelationRiskRule ──────────────────────────────────────────────────────


async def test_correlation_risk_allows_uncorrelated_symbols(monkeypatch) -> None:
    """Low correlation between symbols → no rejection.

    We make one series constant — `correlation` returns 0.0 when either
    series has zero variance (degenerate input guard).
    """
    from platform.risk.rules.correlation_risk import CorrelationRiskRule

    fake_db = _fake_session_factory(open_symbols=["EURUSD"])
    monkeypatch.setattr("platform.risk.rules.correlation_risk.db_context", fake_db)
    rule = CorrelationRiskRule(max_correlation=0.85, lookback_bars=50)

    async def fake_load_closes(session, symbol):
        if symbol == "XAUUSD":
            # Constant series → zero variance → correlation() returns 0.0.
            return [100.0] * 50
        return [200.0 - i for i in range(50)]

    rule._load_closes = fake_load_closes  # type: ignore[assignment]

    await rule.evaluate(_ctx(symbol="XAUUSD"))


async def test_correlation_risk_blocks_highly_correlated_symbols(monkeypatch) -> None:
    """Correlation > threshold raises RiskLimitBreached."""
    from platform.risk.rules.correlation_risk import CorrelationRiskRule

    fake_db = _fake_session_factory(open_symbols=["EURUSD"])
    monkeypatch.setattr("platform.risk.rules.correlation_risk.db_context", fake_db)
    rule = CorrelationRiskRule(max_correlation=0.85, lookback_bars=50)

    async def fake_load_closes(session, symbol):
        return [100.0 + i for i in range(50)]  # identical series → corr=1.0

    rule._load_closes = fake_load_closes  # type: ignore[assignment]

    with pytest.raises(RiskLimitBreached):
        await rule.evaluate(_ctx(symbol="XAUUSD"))


async def test_correlation_risk_no_op_without_open_positions(monkeypatch) -> None:
    """If there are no existing open positions, the rule short-circuits."""
    from platform.risk.rules.correlation_risk import CorrelationRiskRule

    fake_db = _fake_session_factory(open_symbols=[])
    monkeypatch.setattr("platform.risk.rules.correlation_risk.db_context", fake_db)
    rule = CorrelationRiskRule(max_correlation=0.85)
    await rule.evaluate(_ctx())  # should not raise


def test_correlation_helper_returns_zero_for_short_series() -> None:
    """<2 data points → 0.0 (degenerate)."""
    from platform.risk.rules.correlation_risk import correlation

    assert correlation([1.0], [2.0]) == 0.0


def test_correlation_helper_returns_one_for_identical_series() -> None:
    """Identical series → perfect positive correlation."""
    from platform.risk.rules.correlation_risk import correlation

    a = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert correlation(a, a) == pytest.approx(1.0)


# ── SpreadProtectionRule ─────────────────────────────────────────────────────


async def test_spread_protection_allows_tight_spread(local_only_bus) -> None:
    """A normal spread → no rejection."""
    from platform.risk.rules.spread_protection import SpreadProtectionRule

    rule = SpreadProtectionRule(max_spread_points=50.0, max_spread_pct=0.001)
    await rule.update_tick("XAUUSD", bid=2000.0, ask=2000.1)  # tight spread
    await rule.evaluate(_ctx(symbol="XAUUSD"))


async def test_spread_protection_blocks_wide_spread(local_only_bus) -> None:
    """A spread wider than the absolute cap raises RiskLimitBreached."""
    from platform.risk.rules.spread_protection import SpreadProtectionRule

    rule = SpreadProtectionRule(max_spread_points=5.0, max_spread_pct=0.01)
    # Spread = 1.0 → 1.0 / 0.00001 = 100_000 points (way over cap).
    await rule.update_tick("XAUUSD", bid=2000.0, ask=2001.0)
    with pytest.raises(RiskLimitBreached):
        await rule.evaluate(_ctx(symbol="XAUUSD"))


async def test_spread_protection_fails_open_without_tick_data(local_only_bus) -> None:
    """No cached tick → rule fails open (no rejection)."""
    from platform.risk.rules.spread_protection import SpreadProtectionRule

    rule = SpreadProtectionRule()
    await rule.evaluate(_ctx(symbol="UNKNOWN"))  # should not raise


async def test_spread_protection_blocks_crossed_quote(local_only_bus) -> None:
    """A crossed quote (bid > ask) raises RiskLimitBreached."""
    from platform.risk.rules.spread_protection import SpreadProtectionRule

    rule = SpreadProtectionRule()
    await rule.update_tick("XAUUSD", bid=2010.0, ask=2000.0)  # crossed
    with pytest.raises(RiskLimitBreached):
        await rule.evaluate(_ctx(symbol="XAUUSD"))


# ── NewsLockRule ─────────────────────────────────────────────────────────────


def test_news_lock_symbol_to_currency_mapping() -> None:
    """Symbol → currency heuristics for news filtering (quote currency)."""
    from platform.risk.rules.news_lock import symbol_to_currency

    # FX pairs map to their QUOTE currency (the one whose news moves them).
    assert symbol_to_currency("EURUSD") == "USD"
    assert symbol_to_currency("GBPJPY") == "JPY"
    # Metals and crypto end in USD → USD.
    assert symbol_to_currency("XAUUSD") == "USD"
    assert symbol_to_currency("BTCUSD") == "USD"
    # Indices use the first two chars as a country code.
    assert symbol_to_currency("US30") == "US"


async def test_news_lock_blocks_inside_blackout_window() -> None:
    """An order within the news blackout window raises RiskLimitBreached."""
    from datetime import datetime, timedelta
    from platform.risk.rules.news_lock import NewsLockRule

    rule = NewsLockRule(blackout_before_minutes=5, blackout_after_minutes=15)
    now = datetime.now(UTC)
    rule.add_event(
        ts=now + timedelta(minutes=2),  # event in 2 min — we're inside pre-event blackout
        currency="USD",
        impact="high",
        description="NFP",
    )
    with pytest.raises(RiskLimitBreached):
        await rule.evaluate(_ctx(symbol="XAUUSD"))  # XAUUSD → USD


async def test_news_lock_allows_outside_blackout_window() -> None:
    """An order well outside any blackout window passes."""
    from datetime import datetime, timedelta
    from platform.risk.rules.news_lock import NewsLockRule

    rule = NewsLockRule(blackout_before_minutes=5, blackout_after_minutes=15)
    now = datetime.now(UTC)
    rule.add_event(
        ts=now + timedelta(hours=2),  # event in 2 hours — outside blackout
        currency="USD",
        impact="high",
        description="FOMC",
    )
    await rule.evaluate(_ctx(symbol="XAUUSD"))  # should not raise


async def test_news_lock_ignores_low_impact_events_by_default() -> None:
    """Low-impact events don't trigger the blackout when high_impact_only=True."""
    from datetime import datetime, timedelta
    from platform.risk.rules.news_lock import NewsLockRule

    rule = NewsLockRule(high_impact_only=True)
    now = datetime.now(UTC)
    rule.add_event(
        ts=now + timedelta(minutes=2),
        currency="USD",
        impact="low",
        description="Minor data",
    )
    await rule.evaluate(_ctx(symbol="XAUUSD"))  # should not raise


def test_news_lock_purge_old_events_drops_elapsed() -> None:
    """purge_old_events drops events whose blackout window has elapsed."""
    from datetime import datetime, timedelta
    from platform.risk.rules.news_lock import NewsLockRule

    rule = NewsLockRule(blackout_after_minutes=15)
    now = datetime.now(UTC)
    rule.add_event(
        ts=now - timedelta(hours=2),
        currency="USD",
        impact="high",
        description="Old news",
    )
    rule.purge_old_events()
    assert rule._events == []


# ── VolatilityLockRule ───────────────────────────────────────────────────────


async def test_volatility_lock_allows_normal_atr() -> None:
    """ATR% below threshold → no rejection."""
    from platform.risk.rules.volatility_lock import VolatilityLockRule

    rule = VolatilityLockRule(max_atr_pct=0.025)
    await rule.update_atr("XAUUSD", atr=10.0, price=2000.0)  # 0.5% ATR
    await rule.evaluate(_ctx(symbol="XAUUSD"))


async def test_volatility_lock_blocks_extreme_atr() -> None:
    """ATR% above threshold raises RiskLimitBreached."""
    from platform.risk.rules.volatility_lock import VolatilityLockRule

    rule = VolatilityLockRule(max_atr_pct=0.025)
    # 100/2000 = 5% ATR — well above the 2.5% cap.
    await rule.update_atr("XAUUSD", atr=100.0, price=2000.0)
    with pytest.raises(RiskLimitBreached):
        await rule.evaluate(_ctx(symbol="XAUUSD"))


async def test_volatility_lock_cooldown_persists_after_atr_returns_to_normal() -> None:
    """After a spike, the cooldown blocks new orders even with normal ATR."""
    from platform.risk.rules.volatility_lock import VolatilityLockRule

    rule = VolatilityLockRule(max_atr_pct=0.025, cooldown_minutes=30)
    # First call: triggers cooldown.
    await rule.update_atr("XAUUSD", atr=100.0, price=2000.0)
    # Replace ATR with a normal value (without clearing cooldown).
    rule._atr["XAUUSD"] = (10.0, 2000.0)  # type: ignore[index]
    # Cooldown still active — should raise.
    with pytest.raises(RiskLimitBreached):
        await rule.evaluate(_ctx(symbol="XAUUSD"))


async def test_volatility_lock_fails_open_without_atr_data() -> None:
    """No ATR data → rule fails open (no rejection)."""
    from platform.risk.rules.volatility_lock import VolatilityLockRule

    rule = VolatilityLockRule()
    await rule.evaluate(_ctx(symbol="UNKNOWN"))  # should not raise


# ── KellySizingRule ──────────────────────────────────────────────────────────


def test_kelly_helper_zero_for_zero_loss() -> None:
    """avg_loss ≤ 0 → 0.0 (degenerate)."""
    from platform.risk.rules.kelly_sizing import kelly

    assert kelly(0.6, avg_win=2.0, avg_loss=0.0) == 0.0


def test_kelly_helper_zero_for_zero_win_rate() -> None:
    """win_rate ≤ 0 → 0.0."""
    from platform.risk.rules.kelly_sizing import kelly

    assert kelly(0.0, avg_win=2.0, avg_loss=1.0) == 0.0


def test_kelly_helper_clamps_to_one() -> None:
    """Full Kelly cannot exceed 1.0."""
    from platform.risk.rules.kelly_sizing import kelly

    f = kelly(0.99, avg_win=10.0, avg_loss=1.0)
    assert 0.0 <= f <= 1.0


async def test_kelly_sizing_never_rejects(monkeypatch) -> None:
    """KellySizingRule never raises — it only records a suggestion."""
    from platform.risk.rules.kelly_sizing import KellySizingRule

    fake_db = _fake_session_factory(pnls=[])
    monkeypatch.setattr("platform.risk.rules.kelly_sizing.db_context", fake_db)
    rule = KellySizingRule(cap_fraction=0.25, min_trades_for_stats=20)
    ctx = _ctx(volume=0.10)
    ctx.meta = {"strategy_id": uuid4(), "account_equity": 10_000.0, "stop_distance": 0.01}  # type: ignore[attr-defined]
    await rule.evaluate(ctx)
    suggestion = rule.get_suggestion(ctx.terminal_id, ctx.symbol)
    assert suggestion is not None
    assert suggestion >= 0.0


async def test_kelly_sizing_uses_defaults_without_strategy_id() -> None:
    """Without a strategy_id, the rule uses default win_rate / payoff."""
    from platform.risk.rules.kelly_sizing import KellySizingRule

    rule = KellySizingRule(cap_fraction=0.25, default_win_rate=0.5, default_payoff=1.5)
    ctx = _ctx(volume=1.0)
    ctx.meta = {}  # type: ignore[attr-defined]
    await rule.evaluate(ctx)
    # Default win_rate=0.5, payoff=1.5 → kelly = (0.5*1.5 - 0.5)/1.5 = 0.167
    # capped to 0.25 → 0.167. Suggested = 1.0 * 0.167 = 0.167.
    suggestion = rule.get_suggestion(ctx.terminal_id, ctx.symbol)
    assert suggestion is not None
    assert suggestion == pytest.approx(0.167, abs=0.01)


# ── register_all_rules ───────────────────────────────────────────────────────


async def test_register_all_rules_wires_all_eight(local_only_bus, monkeypatch) -> None:
    """register_all_rules adds every rule in ALL_RULES to the engine."""
    import platform.events.bus as bus_mod
    from platform.events.bus import EventBus
    from platform.risk.engine import RiskEngine
    from platform.risk.rules import ALL_RULES, register_all_rules

    fresh = EventBus()
    fresh._local_only = True  # type: ignore[attr-defined]
    monkeypatch.setattr(bus_mod, "get_event_bus", lambda: fresh)

    eng = RiskEngine()
    initial_count = len(eng._rules)
    register_all_rules(eng)
    # 3 built-in rules (kill_switch, max_daily_loss, max_drawdown) + 8 from pack.
    assert len(eng._rules) == initial_count + len(ALL_RULES)
    assert len(ALL_RULES) == 8
