"""Breakout strategy — Donchian channel or Bollinger Band breakout with confirmation.

A classic trend-following approach: wait for price to break above the
recent high (or below the recent low) and ride the continuation. Two modes
are supported:

* **Donchian channel** (default) — upper = highest high over `period`,
  lower = lowest low over `period`. The Turtle Traders' original rule.
* **Bollinger Band** — upper/lower = SMA(period) ± `bb_std` * stddev.
  Tighter, mean-aware envelope.

To reduce false breakouts (the #1 killer of naive breakout systems), a
`confirmation_bars` filter requires N consecutive closes beyond the channel
before the signal fires.

Best use case: trending markets, swing timeframes (H1–D1). In choppy
conditions, expect whipsaws; pair with an ADX / regime filter.

Parameters
----------
channel_period : int
    Lookback length for the channel (default 20).
use_bollinger : bool
    If True, use Bollinger Bands instead of Donchian (default False).
bb_std : float
    Standard-deviation multiplier for Bollinger mode (default 2.0).
min_strength : float
    Minimum strength required to emit a signal.
confirmation_bars : int
    Number of consecutive closes beyond the channel required (default 2).
"""

from __future__ import annotations

from collections import deque
from platform.strategies.sdk import Bar, Signal, Strategy, StrategyContext, strategy
from typing import Any


def donchian(highs: list[float], lows: list[float], period: int) -> tuple[float, float]:
    """Return (upper, lower) Donchian channel using the last `period` bars."""
    if len(highs) < period:
        return max(highs), min(lows)
    upper = max(highs[-period:])
    lower = min(lows[-period:])
    return upper, lower


def bollinger(prices: list[float], period: int, std: float) -> tuple[float, float, float]:
    """Return (upper, middle, lower) Bollinger Bands for the latest bar."""
    if len(prices) < period:
        mid = sum(prices) / len(prices) if prices else 0.0
        return mid, mid, mid
    window = prices[-period:]
    mid = sum(window) / period
    var = sum((p - mid) ** 2 for p in window) / period
    sd = var**0.5
    return mid + std * sd, mid, mid - std * sd


@strategy
class BreakoutStrategy(Strategy):
    name = "breakout"
    version = "1.0.0"
    default_config: dict[str, Any] = {
        "channel_period": 20,
        "use_bollinger": False,
        "bb_std": 2.0,
        "min_strength": 0.6,
        "confirmation_bars": 2,
    }

    def __init__(
        self,
        *,
        channel_period: int = 20,
        use_bollinger: bool = False,
        bb_std: float = 2.0,
        min_strength: float = 0.6,
        confirmation_bars: int = 2,
    ) -> None:
        self.channel_period = channel_period
        self.use_bollinger = use_bollinger
        self.bb_std = bb_std
        self.min_strength = min_strength
        self.confirmation_bars = confirmation_bars
        self._highs: deque[float] = deque(maxlen=channel_period + confirmation_bars + 5)
        self._lows: deque[float] = deque(maxlen=channel_period + confirmation_bars + 5)
        self._closes: deque[float] = deque(maxlen=channel_period + confirmation_bars + 5)
        self._bull_confirm: int = 0
        self._bear_confirm: int = 0

    async def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal | None:
        if not bar.is_closed:
            return None
        # IMPORTANT: append *before* computing the channel so the current bar
        # is excluded — breakouts must reference the prior window only.
        prior_highs = list(self._highs)
        prior_lows = list(self._lows)
        prior_closes = list(self._closes)
        self._highs.append(bar.high)
        self._lows.append(bar.low)
        self._closes.append(bar.close)
        if len(prior_closes) < self.channel_period:
            return None

        if self.use_bollinger:
            upper, mid, lower = bollinger(prior_closes, self.channel_period, self.bb_std)
        else:
            upper, lower = donchian(prior_highs, prior_lows, self.channel_period)
            mid = (upper + lower) / 2.0

        # Count confirmation bars — consecutive closes beyond the channel
        if bar.close > upper:
            self._bull_confirm += 1
            self._bear_confirm = 0
        elif bar.close < lower:
            self._bear_confirm += 1
            self._bull_confirm = 0
        else:
            self._bull_confirm = 0
            self._bear_confirm = 0

        if self._bull_confirm >= self.confirmation_bars:
            band_width = upper - lower
            strength = min(1.0, 0.5 + (bar.close - upper) / (band_width + 1e-9) * 0.5)
            if strength >= self.min_strength:
                # Reset to avoid spamming every bar after breakout
                self._bull_confirm = 0
                return Signal(
                    symbol=bar.symbol,
                    side="buy",
                    strength=strength,
                    suggested_stop_loss=lower,
                    meta={
                        "upper": upper,
                        "lower": lower,
                        "mid": mid,
                        "mode": "bb" if self.use_bollinger else "donchian",
                        "tf": bar.timeframe,
                    },
                )

        if self._bear_confirm >= self.confirmation_bars:
            band_width = upper - lower
            strength = min(1.0, 0.5 + (lower - bar.close) / (band_width + 1e-9) * 0.5)
            if strength >= self.min_strength:
                self._bear_confirm = 0
                return Signal(
                    symbol=bar.symbol,
                    side="sell",
                    strength=strength,
                    suggested_stop_loss=upper,
                    meta={
                        "upper": upper,
                        "lower": lower,
                        "mid": mid,
                        "mode": "bb" if self.use_bollinger else "donchian",
                        "tf": bar.timeframe,
                    },
                )
        return None
