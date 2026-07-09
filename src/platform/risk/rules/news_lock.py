"""News lock rule — blackout trading around scheduled high-impact news.

Economic-calendar releases (NFP, CPI, FOMC, ECB, …) routinely produce
20+ pip spikes in milliseconds. Most strategies are not designed for that
regime — they're built for the order-flow context that exists *between*
news events. This rule enforces a configurable blackout window before
and after each event, scoped by currency.

Symbols are mapped to a base currency via :func:`symbol_to_currency`
(e.g. ``EURUSD`` → ``EUR``, ``XAUUSD`` → ``USD``, ``US30`` → ``US``).
Events are injected via :meth:`add_event`; :meth:`purge_old_events`
should be called periodically to keep the in-memory list bounded.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from platform.core.exceptions import RiskLimitBreached
from platform.core.logging import get_logger
from platform.risk.engine import OrderContext, RiskRule

_log = get_logger(__name__)


def symbol_to_currency(symbol: str) -> str:
    """Map a trading symbol to its base (news-relevant) currency.

    Heuristics: ``XXXYYY`` 6-char FX → base ``XXX``; metals ``XAU/XAG``
    and energy ``XTI/XBR`` → ``USD``; crypto ending ``USD/USDT`` → ``USD``;
    indices (``US30``, ``UK100``, ``GER30`` …) → first two chars as a
    coarse country code (``US``, ``UK``, ``GE``).
    """
    s = symbol.upper().strip()
    if s.startswith(("XAU", "XAG", "XTI", "XBR")):
        return "USD"
    if s.endswith(("USD", "USDT")):
        return "USD"
    for cc in ("EUR", "GBP", "JPY", "CHF"):
        if s.endswith(cc):
            return cc
    if len(s) == 6 and s[:3].isalpha() and s[3:].isalpha():
        return s[:3]
    if len(s) >= 2 and s[:2].isalpha():
        return s[:2]
    return "USD"


class NewsLockRule(RiskRule):
    """Reject orders that fall inside a blackout window around scheduled news."""

    name = "news_lock"

    def __init__(
        self,
        blackout_before_minutes: int = 5,
        blackout_after_minutes: int = 15,
        high_impact_only: bool = True,
    ) -> None:
        """Configure the rule.

        Parameters
        ----------
        blackout_before_minutes:
            Minutes before the event during which new orders are blocked.
        blackout_after_minutes:
            Minutes after the event during which new orders are blocked.
        high_impact_only:
            If ``True``, only ``impact == "high"`` events trigger the
            blackout. If ``False``, medium-impact events also count.
        """
        self.blackout_before = timedelta(minutes=blackout_before_minutes)
        self.blackout_after = timedelta(minutes=blackout_after_minutes)
        self.high_impact_only = high_impact_only
        # In-memory event list: list of (ts, currency, impact, description)
        self._events: list[tuple[datetime, str, str, str]] = []

    def add_event(self, ts: datetime, currency: str, impact: str, description: str) -> None:
        """Inject a news event into the in-memory calendar.

        Parameters
        ----------
        ts:
            Event release time (UTC-aware recommended).
        currency:
            ISO currency code affected (e.g. ``"USD"``, ``"EUR"``).
        impact:
            ``"high"``, ``"medium"``, or ``"low"``.
        description:
            Human-readable label (e.g. ``"Non-Farm Employment Change"``).
        """
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        self._events.append((ts, currency.upper(), impact.lower(), description))

    def purge_old_events(self) -> None:
        """Drop events whose blackout window has fully elapsed.

        Call this from a periodic task (e.g. every minute) to keep the
        in-memory list bounded.
        """
        cutoff = datetime.now(UTC) - self.blackout_after
        before = len(self._events)
        self._events = [e for e in self._events if e[0] > cutoff]
        dropped = before - len(self._events)
        if dropped:
            _log.debug("news_lock_purged", dropped=dropped, remaining=len(self._events))

    async def evaluate(self, ctx: OrderContext) -> None:
        """Reject if current time is inside any blackout window for the symbol's currency.

        Raises
        ------
        RiskLimitBreached
            If the order's currency has a high-impact (or, when configured,
            medium-impact) news event within the blackout window.
        """
        now = datetime.now(UTC)
        currency = symbol_to_currency(ctx.symbol)
        now - self.blackout_before
        now + self.blackout_after

        for ev_ts, ev_ccy, ev_impact, ev_desc in self._events:
            if ev_ccy != currency:
                continue
            if self.high_impact_only and ev_impact != "high":
                continue
            # Blackout = [ev_ts - before, ev_ts + after]
            if (ev_ts - self.blackout_before) <= now <= (ev_ts + self.blackout_after):
                raise RiskLimitBreached(
                    f"news_lock: {currency} event '{ev_desc}' at "
                    f"{ev_ts.isoformat()} — blackout until "
                    f"{(ev_ts + self.blackout_after).isoformat()}"
                )

        _log.debug("news_lock_ok", symbol=ctx.symbol, currency=currency, events=len(self._events))
