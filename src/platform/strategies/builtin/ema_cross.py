"""EMA Cross strategy — canonical example showing the SDK in action.

Two EMAs (fast/slow). On a closed bar, when the fast crosses above the slow,
emit a BUY signal; when it crosses below, emit SELL.
"""
from __future__ import annotations

from collections import deque
from typing import Any

from platform.strategies.sdk import Bar, Signal, Strategy, StrategyContext, strategy


def ema(prev: float, value: float, period: int) -> float:
    if prev == 0:
        return value
    alpha = 2 / (period + 1)
    return alpha * value + (1 - alpha) * prev


@strategy
class EMACrossStrategy(Strategy):
    name = "ema_cross"
    version = "1.0.0"
    default_config = {"fast_period": 9, "slow_period": 21, "min_strength": 0.6}

    def __init__(self, *, fast_period: int = 9, slow_period: int = 21, min_strength: float = 0.6) -> None:
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.min_strength = min_strength
        self._prices: deque[float] = deque(maxlen=slow_period + 5)
        self._prev_fast = 0.0
        self._prev_slow = 0.0
        self._cur_fast = 0.0
        self._cur_slow = 0.0

    async def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal | None:
        if not bar.is_closed:
            return None
        self._prices.append(bar.close)
        if len(self._prices) < self.slow_period:
            return None

        self._prev_fast, self._prev_slow = self._cur_fast, self._cur_slow
        self._cur_fast = ema(self._cur_fast, bar.close, self.fast_period)
        self._cur_slow = ema(self._cur_slow, bar.close, self.slow_period)

        # Detect cross
        prev_diff = self._prev_fast - self._prev_slow
        cur_diff = self._cur_fast - self._cur_slow
        if prev_diff == 0:
            return None

        # Bullish cross
        if prev_diff < 0 and cur_diff > 0:
            strength = min(1.0, abs(cur_diff) / bar.close * 1000)
            if strength < self.min_strength:
                return None
            return Signal(
                symbol=bar.symbol, side="buy", strength=strength,
                meta={"fast": self._cur_fast, "slow": self._cur_slow, "tf": bar.timeframe},
            )
        # Bearish cross
        if prev_diff > 0 and cur_diff < 0:
            strength = min(1.0, abs(cur_diff) / bar.close * 1000)
            if strength < self.min_strength:
                return None
            return Signal(
                symbol=bar.symbol, side="sell", strength=strength,
                meta={"fast": self._cur_fast, "slow": self._cur_slow, "tf": bar.timeframe},
            )
        return None
