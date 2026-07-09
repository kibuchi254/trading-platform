"""MACD Divergence strategy — fade trend exhaustion via classic divergence.

Divergence is one of the most reliable reversal signals: when price makes a
new extreme but the MACD histogram fails to confirm, momentum is waning and
a reversal is likely.

This module detects two patterns over a sliding lookback window:

* **Bullish divergence** — price prints a *lower low*, but the MACD
  histogram prints a *higher low*. Traders expect price to reverse up.
* **Bearish divergence** — price prints a *higher high*, but the MACD
  histogram prints a *lower high*. Traders expect price to reverse down.

Best use case: swing trading reversals at the end of extended trends, on H1
or higher timeframes. Lower timeframes are noisy and produce false
divergences.

Parameters
----------
fast, slow, signal : int
    Standard MACD periods (12 / 26 / 9).
lookback : int
    Number of recent bars used to locate the previous swing extreme (default 20).
min_strength : float
    Minimum strength threshold; strength scales with how sharp the divergence is.
"""

from __future__ import annotations

from collections import deque
from platform.strategies.sdk import Bar, Signal, Strategy, StrategyContext, strategy
from typing import Any


def ema(values: list[float], period: int) -> list[float]:
    """Full EMA series aligned with `values`. Uses standard SMA seed."""
    n = len(values)
    out: list[float] = [0.0] * n
    if n == 0:
        return out
    alpha = 2.0 / (period + 1)
    seed = sum(values[: min(period, n)]) / min(period, n)
    out[min(period, n) - 1] = seed
    for i in range(min(period, n), n):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    # Back-fill leading zeros with the seed so length stays aligned
    for i in range(min(period, n) - 1):
        out[i] = seed
    return out


def macd(
    prices: list[float], fast: int, slow: int, signal: int
) -> tuple[list[float], list[float], list[float]]:
    """Return (macd_line, signal_line, histogram) series aligned with prices."""
    ema_fast = ema(prices, fast)
    ema_slow = ema(prices, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow, strict=False)]
    signal_line = ema(macd_line, signal)
    histogram = [m - s for m, s in zip(macd_line, signal_line, strict=False)]
    return macd_line, signal_line, histogram


@strategy
class MACDDivergenceStrategy(Strategy):
    name = "macd_divergence"
    version = "1.0.0"
    default_config: dict[str, Any] = {
        "fast": 12,
        "slow": 26,
        "signal": 9,
        "lookback": 20,
        "min_strength": 0.55,
    }

    def __init__(
        self,
        *,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
        lookback: int = 20,
        min_strength: float = 0.55,
    ) -> None:
        self.fast = fast
        self.slow = slow
        self.signal = signal
        self.lookback = lookback
        self.min_strength = min_strength
        self._prices: deque[float] = deque(maxlen=max(slow + signal + lookback, 100))
        self._last_signal_index = -1

    async def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal | None:
        if not bar.is_closed:
            return None
        self._prices.append(bar.close)
        needed = self.slow + self.signal + self.lookback
        if len(self._prices) < needed:
            return None

        prices = list(self._prices)
        macd_line, signal_line, hist = macd(prices, self.fast, self.slow, self.signal)

        # Locate the most recent confirmed swing in the lookback window.
        window_prices = prices[-self.lookback :]
        window_hist = hist[-self.lookback :]
        cur_price = prices[-1]
        cur_hist = hist[-1]

        # Find previous swing low (local minimum of price within the window, excluding the last bar)
        prev_low_idx = int(min(range(len(window_prices) - 1), key=lambda i: window_prices[i]))
        prev_low_price = window_prices[prev_low_idx]
        prev_low_hist = window_hist[prev_low_idx]

        prev_high_idx = int(max(range(len(window_prices) - 1), key=lambda i: window_prices[i]))
        prev_high_price = window_prices[prev_high_idx]
        prev_high_hist = window_hist[prev_high_idx]

        meta_base = {
            "macd": macd_line[-1],
            "signal": signal_line[-1],
            "hist": cur_hist,
            "tf": bar.timeframe,
        }

        # Bullish divergence: lower low in price, higher low in histogram
        if cur_price < prev_low_price and cur_hist > prev_low_hist:
            price_drop = (prev_low_price - cur_price) / prev_low_price if prev_low_price else 0.0
            hist_lift = cur_hist - prev_low_hist
            strength = min(1.0, 0.4 + price_drop * 5 + abs(hist_lift) * 50)
            if strength >= self.min_strength:
                return Signal(
                    symbol=bar.symbol,
                    side="buy",
                    strength=strength,
                    meta={**meta_base, "divergence": "bullish"},
                )

        # Bearish divergence: higher high in price, lower high in histogram
        if cur_price > prev_high_price and cur_hist < prev_high_hist:
            price_rise = (cur_price - prev_high_price) / prev_high_price if prev_high_price else 0.0
            hist_drop = prev_high_hist - cur_hist
            strength = min(1.0, 0.4 + price_rise * 5 + abs(hist_drop) * 50)
            if strength >= self.min_strength:
                return Signal(
                    symbol=bar.symbol,
                    side="sell",
                    strength=strength,
                    meta={**meta_base, "divergence": "bearish"},
                )
        return None
