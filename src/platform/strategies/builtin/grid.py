"""Grid trading strategy — symmetric grid around an anchor price.

Grid trading profits from mean-reverting noise: the bot pre-defines a ladder
of equally spaced price levels above and below an anchor. As price moves up
through a level it sells (sell the rally), and as price moves down through a
level it buys (buy the dip). Each fill carries a tight take-profit at
`± take_profit_pct` from the fill price.

The grid is anchored on the first closed bar received. The strategy is
*directionally neutral*: in a ranging market it slowly harvests the spread;
in a strong trend it accumulates a losing position that the take-profit
levels cannot rescue, so a hard equity stop should be enforced upstream.

Best use case: sideways FX / crypto pairs during low-volatility sessions,
or as a yield layer on top of a slow-moving core position.

Parameters
----------
grid_levels : int
    Number of grid levels on *each side* of the anchor (default 10).
grid_spacing_pct : float
    Distance between adjacent levels as a fraction of anchor (default 0.005 = 0.5%).
base_volume : float
    Volume per grid fill (default 0.01).
take_profit_pct : float
    Take-profit distance from each fill (default 0.003 = 0.3%).
"""

from __future__ import annotations

from platform.strategies.sdk import Bar, Signal, Strategy, StrategyContext, strategy
from typing import Any


@strategy
class GridStrategy(Strategy):
    name = "grid"
    version = "1.0.0"
    default_config: dict[str, Any] = {
        "grid_levels": 10,
        "grid_spacing_pct": 0.005,
        "base_volume": 0.01,
        "take_profit_pct": 0.003,
    }

    def __init__(
        self,
        *,
        grid_levels: int = 10,
        grid_spacing_pct: float = 0.005,
        base_volume: float = 0.01,
        take_profit_pct: float = 0.003,
    ) -> None:
        self.grid_levels = grid_levels
        self.grid_spacing_pct = grid_spacing_pct
        self.base_volume = base_volume
        self.take_profit_pct = take_profit_pct
        self._anchor: float | None = None
        # Pre-computed prices for each level index (-N .. +N)
        self._levels: dict[int, float] = {}
        # Filled level indices — prevents re-firing on every bar within the same band
        self._filled: set[int] = set()
        self._last_band: int | None = None

    def _build_grid(self, anchor: float) -> None:
        self._levels = {}
        for k in range(-self.grid_levels, self.grid_levels + 1):
            self._levels[k] = anchor * (1.0 + k * self.grid_spacing_pct)

    def _band_for(self, price: float) -> int:
        """Return the grid level index immediately below `price`."""
        if price >= self._levels[self.grid_levels]:
            return self.grid_levels
        if price <= self._levels[-self.grid_levels]:
            return -self.grid_levels
        # Binary-ish scan — grids are small, linear scan is fine
        prev_k = -self.grid_levels
        for k in range(-self.grid_levels + 1, self.grid_levels + 1):
            if self._levels[k] > price:
                return prev_k
            prev_k = k
        return prev_k

    async def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal | None:
        if not bar.is_closed:
            return None
        if self._anchor is None:
            self._anchor = bar.close
            self._build_grid(bar.close)
            self._last_band = self._band_for(bar.close)
            return None

        band = self._band_for(bar.close)
        last = self._last_band
        self._last_band = band
        if last is None or band == last:
            return None

        # Crossed upward through one or more levels — emit SELL at each fresh level
        if band > last:
            for k in range(last + 1, band + 1):
                if k in self._filled or k not in self._levels:
                    continue
                self._filled.add(k)
                # Allow the opposite-side level to re-fill on return
                opposite = -k
                self._filled.discard(opposite)
                return Signal(
                    symbol=bar.symbol,
                    side="sell",
                    strength=0.7,
                    suggested_volume=self.base_volume,
                    suggested_take_profit=self._levels[k] * (1.0 - self.take_profit_pct),
                    meta={
                        "grid_level": k,
                        "anchor": self._anchor,
                        "price": self._levels[k],
                        "tf": bar.timeframe,
                    },
                )

        # Crossed downward through one or more levels — emit BUY
        if band < last:
            for k in range(last - 1, band - 1, -1):
                if k in self._filled or k not in self._levels:
                    continue
                self._filled.add(k)
                opposite = -k
                self._filled.discard(opposite)
                return Signal(
                    symbol=bar.symbol,
                    side="buy",
                    strength=0.7,
                    suggested_volume=self.base_volume,
                    suggested_take_profit=self._levels[k] * (1.0 + self.take_profit_pct),
                    meta={
                        "grid_level": k,
                        "anchor": self._anchor,
                        "price": self._levels[k],
                        "tf": bar.timeframe,
                    },
                )
        return None
