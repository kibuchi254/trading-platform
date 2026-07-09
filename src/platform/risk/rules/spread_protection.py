"""Spread protection rule — reject orders when the bid/ask spread blows out.

Spreads widen dramatically around news, low-liquidity sessions, and
broker-side outages. Trading into a fat spread is the textbook way to
give back edge. This rule reads the latest tick from an in-memory cache
maintained by subscribing to ``atlas.ticks`` and rejects orders when the
spread exceeds either an absolute threshold (in points) or a relative
threshold (as a fraction of mid).

Two thresholds are enforced independently — a breach of either rejects:

* ``max_spread_points`` — absolute spread in points (1 point = the
  smallest price increment for the symbol; we approximate using 1e-5
  for 5-digit FX and 1e-2 for indices — the rule is intentionally
  conservative).
* ``max_spread_pct`` — spread as a fraction of the mid price (e.g.
  ``0.001`` = 10 bps).
"""

from __future__ import annotations

from platform.core.exceptions import RiskLimitBreached
from platform.core.logging import get_logger
from platform.events.bus import get_event_bus
from platform.events.topics import Topic
from platform.risk.engine import OrderContext, RiskRule
from typing import Any

_log = get_logger(__name__)


class SpreadProtectionRule(RiskRule):
    """Reject orders when the live bid/ask spread exceeds configured thresholds."""

    name = "spread_protection"

    def __init__(
        self,
        max_spread_points: float = 50.0,
        max_spread_pct: float = 0.001,
    ) -> None:
        """Configure the rule and subscribe to the tick bus.

        Parameters
        ----------
        max_spread_points:
            Maximum absolute spread in points. A "point" here is the raw
            price increment (e.g. 0.00001 on EURUSD, 0.01 on US30).
        max_spread_pct:
            Maximum spread as a fraction of the mid price (e.g. 0.001 =
            10 basis points).
        """
        self.max_spread_points = max_spread_points
        self.max_spread_pct = max_spread_pct
        # In-memory tick cache: symbol -> (bid, ask, ts)
        self._ticks: dict[str, tuple[float, float, float]] = {}

        bus = get_event_bus()
        bus.subscribe(Topic.TICKS, self._on_tick)
        _log.info("spread_protection_subscribed", topic=Topic.TICKS)

    async def _on_tick(self, payload: dict[str, Any]) -> None:
        """Event-bus handler — updates the in-memory tick cache."""
        symbol = payload.get("symbol")
        bid = payload.get("bid")
        ask = payload.get("ask")
        ts = payload.get("ts") or 0.0
        if symbol is None or bid is None or ask is None:
            return
        try:
            self._ticks[symbol] = (float(bid), float(ask), float(ts))
        except (TypeError, ValueError):
            _log.warning("spread_protection_bad_tick", payload=payload)

    async def update_tick(self, symbol: str, bid: float, ask: float) -> None:
        """Public helper for tests / non-bus tick feeds."""
        self._ticks[symbol] = (float(bid), float(ask), 0.0)

    async def evaluate(self, ctx: OrderContext) -> None:
        """Check the cached spread for ``ctx.symbol`` and reject if too wide.

        Raises
        ------
        RiskLimitBreached
            If the latest spread exceeds ``max_spread_points`` or
            ``max_spread_pct``.
        """
        cached = self._ticks.get(ctx.symbol)
        if cached is None:
            # No tick data yet — fail open (let other rules decide).
            _log.debug("spread_protection_no_tick", symbol=ctx.symbol)
            return

        bid, ask, _ts = cached
        spread_abs = ask - bid
        if spread_abs < 0:
            # Crossed/invalid quote — block defensively.
            raise RiskLimitBreached(
                f"spread_protection: crossed quote on {ctx.symbol} (bid={bid}, ask={ask})"
            )
        mid = (bid + ask) / 2.0
        if mid <= 0:
            return

        # Conservative point-size estimate: 1e-5 for FX-like 5-digit symbols,
        # 1e-2 for index-style 2-digit symbols. Caller can subclass to refine.
        point = 0.00001 if mid < 1000 else 0.01
        spread_points = spread_abs / point
        spread_pct = spread_abs / mid

        if spread_points > self.max_spread_points:
            raise RiskLimitBreached(
                f"spread_protection: spread {spread_points:.1f} points on "
                f"{ctx.symbol} (cap {self.max_spread_points:.1f})"
            )
        if spread_pct > self.max_spread_pct:
            raise RiskLimitBreached(
                f"spread_protection: spread {spread_pct:.4%} on "
                f"{ctx.symbol} (cap {self.max_spread_pct:.4%})"
            )

        _log.debug(
            "spread_protection_ok",
            symbol=ctx.symbol,
            spread_points=spread_points,
            spread_pct=spread_pct,
        )
