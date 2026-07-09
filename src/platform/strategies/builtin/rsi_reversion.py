"""RSI Mean Reversion strategy — buy oversold dips, sell overbought rips.

Computes RSI using Wilder's smoothing (the original Welles Wilder method),
then waits for RSI to *exit* the extreme zone before signalling. This avoids
catching falling knives: we only emit BUY once RSI has crossed back above the
oversold threshold (mean reversion confirmed), and SELL once it crosses back
below the overbought threshold.

Best use case: range-bound / mean-reverting markets on intraday timeframes
(M5–H1). Avoid strong trends — RSI can stay pinned in extreme zones and the
"cross back" signal will fire against the trend.

Parameters
----------
period : int
    RSI lookback length (default 14, the Wilder classic).
oversold : int
    RSI level below which the asset is considered oversold (default 30).
overbought : int
    RSI level above which the asset is considered overbought (default 70).
min_strength : float
    Minimum signal strength to actually emit (default 0.6). Strength is scaled
    by how far RSI has moved back through the threshold.
exit_threshold : int
    RSI midpoint used to optionally scale exit strength (default 50).
"""

from __future__ import annotations

from collections import deque
from platform.strategies.sdk import Bar, Signal, Strategy, StrategyContext, strategy
from typing import Any


def rsi(prices: list[float], period: int) -> list[float]:
    """Compute RSI with Wilder's smoothing method.

    First average gain/loss is a simple mean; subsequent averages use
    Wilder's recursive form: avg = (prev_avg * (period - 1) + cur) / period.
    Returns a list aligned with `prices` (NaN-free; early indices get 50.0
    as a neutral placeholder when insufficient data).
    """
    n = len(prices)
    out: list[float] = [50.0] * n
    if n < period + 1:
        return out
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        diff = prices[i] - prices[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    rs = avg_gain / avg_loss if avg_loss != 0 else float("inf")
    out[period] = 100.0 - (100.0 / (1.0 + rs))
    for i in range(period + 1, n):
        diff = prices[i] - prices[i - 1]
        gain = diff if diff > 0 else 0.0
        loss = -diff if diff < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        rs = avg_gain / avg_loss if avg_loss != 0 else float("inf")
        out[i] = 100.0 - (100.0 / (1.0 + rs))
    return out


@strategy
class RSIReversionStrategy(Strategy):
    name = "rsi_reversion"
    version = "1.0.0"
    default_config: dict[str, Any] = {
        "period": 14,
        "oversold": 30,
        "overbought": 70,
        "min_strength": 0.6,
        "exit_threshold": 50,
    }

    def __init__(
        self,
        *,
        period: int = 14,
        oversold: int = 30,
        overbought: int = 70,
        min_strength: float = 0.6,
        exit_threshold: int = 50,
    ) -> None:
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        self.min_strength = min_strength
        self.exit_threshold = exit_threshold
        self._prices: deque[float] = deque(maxlen=period * 6)
        self._prev_rsi: float = 50.0

    async def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal | None:
        if not bar.is_closed:
            return None
        self._prices.append(bar.close)
        if len(self._prices) < self.period + 2:
            return None

        prices_list = list(self._prices)
        rsi_series = rsi(prices_list, self.period)
        cur_rsi = rsi_series[-1]
        prev_rsi = self._prev_rsi
        self._prev_rsi = cur_rsi

        # Bullish mean-reversion: RSI was below oversold, now crosses back up
        if prev_rsi <= self.oversold and cur_rsi > self.oversold:
            depth = (self.oversold - prev_rsi) / self.oversold if self.oversold else 0.0
            strength = min(1.0, 0.5 + depth * 0.5)
            if strength < self.min_strength:
                return None
            return Signal(
                symbol=bar.symbol,
                side="buy",
                strength=strength,
                meta={
                    "rsi": cur_rsi,
                    "prev_rsi": prev_rsi,
                    "action": "mean_reversion_long",
                    "tf": bar.timeframe,
                },
            )

        # Bearish mean-reversion: RSI was above overbought, now crosses back down
        if prev_rsi >= self.overbought and cur_rsi < self.overbought:
            depth = (
                (prev_rsi - self.overbought) / (100 - self.overbought)
                if self.overbought < 100
                else 0.0
            )
            strength = min(1.0, 0.5 + depth * 0.5)
            if strength < self.min_strength:
                return None
            return Signal(
                symbol=bar.symbol,
                side="sell",
                strength=strength,
                meta={
                    "rsi": cur_rsi,
                    "prev_rsi": prev_rsi,
                    "action": "mean_reversion_short",
                    "tf": bar.timeframe,
                },
            )
        return None
