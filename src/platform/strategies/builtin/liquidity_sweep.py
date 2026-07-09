"""Liquidity Sweep strategy — trade reversal after stop runs.

A *liquidity sweep* (a.k.a. stop hunt, turtle soup) happens when price
briefly penetrates a prior swing extreme to trigger resting stop orders,
then snaps back. This is one of the most reliable reversal triggers in
technical trading because it represents informed money filling positions
against trapped retail.

This strategy:

1. Maintains a rolling window of recent bars.
2. Detects **fractal swing highs and lows** — a pivot high is a bar whose
   high is greater than the `lookback // 2` bars on each side.
3. **Bullish sweep** — bar.low penetrates the most recent swing low by at
   least `sweep_threshold_pct`, but the bar closes back above it. After
   `reversal_confirmation` higher closes, emit BUY.
4. **Bearish sweep** — mirror image for swing highs → emit SELL.

Best use case: H1–H4 on liquid FX majors and index futures. Very effective
around session opens and news-driven liquidity spikes.

Parameters
----------
swing_lookback : int
    Window for fractal swing detection (default 20). Should be odd-ish.
sweep_threshold_pct : float
    Minimum penetration past the swing extreme as a fraction of price
    (default 0.001 = 0.1%).
reversal_confirmation : int
    Number of closes back on the "correct" side required to confirm (default 2).
min_strength : float
    Minimum signal strength threshold.
"""

from __future__ import annotations

from collections import deque
from platform.strategies.sdk import Bar, Signal, Strategy, StrategyContext, strategy
from typing import Any


def find_swings(bars: list[Bar], lookback: int) -> tuple[list[float], list[float]]:
    """Return (swing_highs, swing_lows) using a fractal pivot rule.

    A pivot high at index i requires bars[i].high to be the strict maximum
    of bars[i - half .. i + half] where half = lookback // 2. The lists
    contain the *price* of each detected swing, in chronological order.
    """
    half = lookback // 2
    swing_highs: list[float] = []
    swing_lows: list[float] = []
    n = len(bars)
    for i in range(half, n - half):
        window = bars[i - half : i + half + 1]
        if (
            bars[i].high == max(b.high for b in window)
            and sum(1 for b in window if b.high == bars[i].high) == 1
        ):
            swing_highs.append(bars[i].high)
        if (
            bars[i].low == min(b.low for b in window)
            and sum(1 for b in window if b.low == bars[i].low) == 1
        ):
            swing_lows.append(bars[i].low)
    return swing_highs, swing_lows


@strategy
class LiquiditySweepStrategy(Strategy):
    name = "liquidity_sweep"
    version = "1.0.0"
    default_config: dict[str, Any] = {
        "swing_lookback": 20,
        "sweep_threshold_pct": 0.001,
        "reversal_confirmation": 2,
        "min_strength": 0.65,
    }

    def __init__(
        self,
        *,
        swing_lookback: int = 20,
        sweep_threshold_pct: float = 0.001,
        reversal_confirmation: int = 2,
        min_strength: float = 0.65,
    ) -> None:
        self.swing_lookback = swing_lookback
        self.sweep_threshold_pct = sweep_threshold_pct
        self.reversal_confirmation = reversal_confirmation
        self.min_strength = min_strength
        self._bars: deque[Bar] = deque(maxlen=swing_lookback + 10)
        # Pending sweep state: ("bull"|"bear", swing_extreme, bars_since_sweep)
        self._pending: tuple[str, float, int] | None = None

    async def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal | None:
        if not bar.is_closed:
            return None
        self._bars.append(bar)
        if len(self._bars) < self.swing_lookback + 1:
            return None

        bars = list(self._bars)
        swing_highs, swing_lows = find_swings(bars, self.swing_lookback)

        # Advance any pending confirmation counter first
        if self._pending is not None:
            kind, extreme, count = self._pending
            count += 1
            still_valid = (kind == "bull" and bar.close > extreme) or (
                kind == "bear" and bar.close < extreme
            )
            if not still_valid:
                self._pending = None
            elif count >= self.reversal_confirmation:
                self._pending = None
                strength = min(1.0, 0.6 + count * 0.1)
                if strength < self.min_strength:
                    return None
                side = "buy" if kind == "bull" else "sell"
                tp = extreme * (1.0 + 0.005) if kind == "bull" else extreme * (1.0 - 0.005)
                sl = extreme * (1.0 - 0.003) if kind == "bull" else extreme * (1.0 + 0.003)
                return Signal(
                    symbol=bar.symbol,
                    side=side,
                    strength=strength,
                    suggested_stop_loss=sl,
                    suggested_take_profit=tp,
                    meta={
                        "sweep": kind,
                        "swing_extreme": extreme,
                        "confirmations": count,
                        "tf": bar.timeframe,
                    },
                )
            else:
                self._pending = (kind, extreme, count)

        # Detect fresh sweeps (only when no pending state)
        if self._pending is None:
            if swing_lows:
                recent_low = swing_lows[-1]
                penetration = (recent_low - bar.low) / recent_low if recent_low else 0.0
                if penetration >= self.sweep_threshold_pct and bar.close > recent_low:
                    self._pending = ("bull", recent_low, 0)
            if self._pending is None and swing_highs:
                recent_high = swing_highs[-1]
                penetration = (bar.high - recent_high) / recent_high if recent_high else 0.0
                if penetration >= self.sweep_threshold_pct and bar.close < recent_high:
                    self._pending = ("bear", recent_high, 0)
        return None
