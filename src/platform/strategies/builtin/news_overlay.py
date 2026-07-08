"""News Overlay — risk filter that flattens positions around news events.

This is *not* a directional strategy. It is a **filter** designed to be
stacked alongside other strategies via the orchestrator. Around high-impact
scheduled news (CPI, NFP, FOMC, rate decisions) the strategy emits a special
"flatten" signal which the engine treats as a directive to close existing
exposure and suppress new entries until the blackout window ends.

The signal encoding is intentional and documented for the engine:

    Signal(side="buy", strength=0.0, meta={"action": "flatten", "reason": "news_blackout", ...})

A zero-strength buy is otherwise a no-op, so a naive engine that ignores the
meta block stays safe. A news-aware engine reads `meta["action"] == "flatten"`
and acts accordingly.

Events are injected at runtime via `add_news_event(ts, impact, symbol)` —
typically by a scheduler pulling an economic calendar. Stale events are
pruned automatically.

Best use case: any live trading deployment that runs directional strategies
through scheduled macro releases. Use a wide `blackout_minutes_after` for
events that move the market for an hour or more (FOMC, NFP).

Parameters
----------
blackout_minutes_before : int
    Stop trading this many minutes before a scheduled event (default 5).
blackout_minutes_after : int
    Resume trading this many minutes after the event (default 15).
high_impact_only : bool
    If True, only high-impact events trigger blackouts (default True).
allow_close_existing : bool
    If True, emit the flatten signal so existing positions are closed
    rather than just suppressing new entries (default True).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from platform.strategies.sdk import Bar, Signal, Strategy, StrategyContext, strategy


def is_in_blackout(now: datetime, event_ts: datetime, before_min: int, after_min: int) -> bool:
    """Return True if `now` falls within the blackout window around `event_ts`."""
    start = event_ts - timedelta(minutes=before_min)
    end = event_ts + timedelta(minutes=after_min)
    return start <= now <= end


@strategy
class NewsOverlayStrategy(Strategy):
    name = "news_overlay"
    version = "1.0.0"
    default_config: dict[str, Any] = {
        "blackout_minutes_before": 5,
        "blackout_minutes_after": 15,
        "high_impact_only": True,
        "allow_close_existing": True,
    }

    def __init__(
        self,
        *,
        blackout_minutes_before: int = 5,
        blackout_minutes_after: int = 15,
        high_impact_only: bool = True,
        allow_close_existing: bool = True,
    ) -> None:
        self.blackout_minutes_before = blackout_minutes_before
        self.blackout_minutes_after = blackout_minutes_after
        self.high_impact_only = high_impact_only
        self.allow_close_existing = allow_close_existing
        # Each event: (ts, impact, symbol)
        self._events: list[tuple[datetime, str, str]] = []
        self._last_blackout: bool = False  # avoids spamming flatten on every bar

    def add_news_event(self, ts: datetime, impact: str, symbol: str) -> None:
        """Inject a scheduled news event. `impact` ∈ {"high","medium","low"}."""
        self._events.append((ts, impact, symbol))
        # Keep chronological and bounded
        self._events.sort(key=lambda e: e[0])

    def _prune(self, now: datetime) -> None:
        cutoff = now - timedelta(minutes=self.blackout_minutes_after + 60)
        self._events = [e for e in self._events if e[0] > cutoff]

    async def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal | None:
        # Bar updates drive the clock; use bar.ts as authoritative time
        now = bar.ts
        self._prune(now)

        in_blackout = False
        triggering_event: tuple[datetime, str, str] | None = None
        for event in self._events:
            event_ts, impact, sym = event
            if sym and sym != bar.symbol:
                continue
            if self.high_impact_only and impact != "high":
                continue
            if is_in_blackout(now, event_ts, self.blackout_minutes_before, self.blackout_minutes_after):
                in_blackout = True
                triggering_event = event
                break

        if in_blackout and self.allow_close_existing and not self._last_blackout:
            self._last_blackout = True
            assert triggering_event is not None  # for type checker
            return Signal(
                symbol=bar.symbol,
                side="buy",
                strength=0.0,
                meta={
                    "action": "flatten",
                    "reason": "news_blackout",
                    "event_ts": triggering_event[0].isoformat(),
                    "impact": triggering_event[1],
                    "now": now.isoformat(),
                    "tf": bar.timeframe,
                },
            )

        if not in_blackout:
            self._last_blackout = False
        return None
