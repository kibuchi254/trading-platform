"""SMC Order Blocks + Fair Value Gap (FVG) confluence strategy.

Smart Money Concepts (SMC) describe how institutional flow leaves footprints
on the chart. Two of the most actionable patterns are:

1. **Order Blocks (OB)** — the last opposite-coloured candle before a strong
   impulse move. Institutions supposedly filled there; price tends to react
   when it returns.
2. **Fair Value Gaps (FVG)** — a 3-candle imbalance where candle[i-1].high <
   candle[i+1].low (bullish) or candle[i-1].low > candle[i+1].high (bearish).
   These unfilled zones act as magnets on retests.

This strategy detects both, stores recent OBs in `self._blocks`, and emits a
signal when price returns to a bullish OB that also overlaps a bullish FVG
(or bearish equivalent). The confluence requirement filters out low-quality
touches.

Best use case: intraday FX / index CFDs on M5–M15. Works well when layered
with a higher-timeframe bias filter.

Parameters
----------
lookback : int
    Bars of history scanned for OB / FVG detection.
min_block_size_pct : float
    Minimum body size of the impulse candle, as a fraction of price, to
    qualify as an order block (default 0.001 = 0.1%).
require_fvg : bool
    If True, signals only fire when OB overlaps an FVG (default True).
min_strength : float
    Minimum signal strength threshold.
"""
from __future__ import annotations

from collections import deque
from typing import Any

from platform.strategies.sdk import Bar, Signal, Strategy, StrategyContext, strategy


def _is_bullish_fvg(b_prev: Bar, b_next: Bar) -> bool:
    return b_next.low > b_prev.high


def _is_bearish_fvg(b_prev: Bar, b_next: Bar) -> bool:
    return b_next.high < b_prev.low


@strategy
class SMCOrderBlocksStrategy(Strategy):
    name = "smc_order_blocks"
    version = "1.0.0"
    default_config: dict[str, Any] = {
        "lookback": 50,
        "min_block_size_pct": 0.001,
        "require_fvg": True,
        "min_strength": 0.6,
    }

    def __init__(
        self,
        *,
        lookback: int = 50,
        min_block_size_pct: float = 0.001,
        require_fvg: bool = True,
        min_strength: float = 0.6,
    ) -> None:
        self.lookback = lookback
        self.min_block_size_pct = min_block_size_pct
        self.require_fvg = require_fvg
        self.min_strength = min_strength
        self._bars: deque[Bar] = deque(maxlen=lookback + 10)
        # Each block: (index, type, high, low)
        self._blocks: list[tuple[int, str, float, float]] = []
        # FVG zones: (index, type, top, bottom)
        self._fvgs: list[tuple[int, str, float, float]] = []

    def _scan_blocks_and_fvgs(self, bars: list[Bar]) -> None:
        """Rebuild the OB and FVG caches from the recent bar window."""
        self._blocks = []
        self._fvgs = []
        for i in range(1, len(bars) - 1):
            prev, cur, nxt = bars[i - 1], bars[i], bars[i + 1]
            body_size = abs(cur.close - cur.open)
            ref_price = cur.close or 1.0
            impulse = body_size / ref_price >= self.min_block_size_pct

            # Bullish OB: last bearish candle before a bullish impulse
            if impulse and cur.close > cur.open and prev.close < prev.open:
                self._blocks.append((i, "bullish", prev.high, prev.low))
            # Bearish OB: last bullish candle before a bearish impulse
            if impulse and cur.close < cur.open and prev.close > prev.open:
                self._blocks.append((i, "bearish", prev.high, prev.low))

            # FVG detection uses (prev, nxt) — the candles surrounding `cur`
            if _is_bullish_fvg(prev, nxt):
                self._fvgs.append((i, "bullish", nxt.low, prev.high))
            elif _is_bearish_fvg(prev, nxt):
                self._fvgs.append((i, "bearish", prev.low, nxt.high))

    @staticmethod
    def _overlaps(a_hi: float, a_lo: float, b_hi: float, b_lo: float) -> bool:
        return not (a_hi < b_lo or b_hi < a_lo)

    async def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal | None:
        if not bar.is_closed:
            return None
        self._bars.append(bar)
        if len(self._bars) < 5:
            return None

        bars = list(self._bars)[-self.lookback :]
        self._scan_blocks_and_fvgs(bars)

        price = bar.close
        # Unify bullish/bearish scans: (block_type, side, stop_mult, strength_fn)
        for btype, side, stop_mult, stren_fn in [
            ("bullish", "buy",   0.999, lambda hi, lo, p: min(1.0, 0.5 + (hi - p) / (hi - lo + 1e-9) * 0.5)),
            ("bearish", "sell",  1.001, lambda hi, lo, p: min(1.0, 0.5 + (p - lo) / (hi - lo + 1e-9) * 0.5)),
        ]:
            for (idx, bt, hi, lo) in self._blocks:
                if bt != btype or not (lo <= price <= hi):
                    continue
                if self.require_fvg and not any(
                    ft == btype and self._overlaps(hi, lo, ft_top, ft_bot)
                    for (_, ft, ft_top, ft_bot) in self._fvgs
                ):
                    continue
                strength = stren_fn(hi, lo, price)
                if strength < self.min_strength:
                    continue
                return Signal(
                    symbol=bar.symbol,
                    side=side,
                    strength=strength,
                    suggested_stop_loss=(lo if side == "buy" else hi) * stop_mult,
                    meta={"block": btype, "block_high": hi, "block_low": lo, "tf": bar.timeframe},
                )
        return None
