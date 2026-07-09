"""Volatility lock rule — block trading in symbols whose ATR has blown out.

ATR (Average True Range) measures recent realised volatility in price
units. Normalised by price it becomes a percentage — ``atr_pct = atr /
price`` — that's directly comparable across symbols and asset classes.

When ``atr_pct`` exceeds ``max_atr_pct`` on a symbol, that symbol is
behaving more chaotically than the strategy is calibrated for, and we
block new entries. After a block we enter a per-symbol cooldown — even
if ATR comes back inside the threshold, new orders on that symbol keep
getting rejected for ``cooldown_minutes`` to avoid whipsaw entries at the
edge of a volatility spike.

ATR is supplied externally via :meth:`update_atr` (typically a bar-close
subscriber); the rule itself never queries the candle table.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from platform.core.exceptions import RiskLimitBreached
from platform.core.logging import get_logger
from platform.risk.engine import OrderContext, RiskRule

_log = get_logger(__name__)


class VolatilityLockRule(RiskRule):
    """Reject orders on symbols whose ATR% exceeds threshold or while in cooldown."""

    name = "volatility_lock"

    def __init__(
        self,
        max_atr_pct: float = 0.025,
        atr_period: int = 14,
        cooldown_minutes: int = 30,
    ) -> None:
        """Configure the rule.

        Parameters
        ----------
        max_atr_pct:
            Maximum tolerated ``atr / price`` ratio (e.g. ``0.025`` = 2.5%).
        atr_period:
            ATR period in bars (informational — used only for logging; the
            actual ATR value is supplied externally).
        cooldown_minutes:
            Duration of the per-symbol block after a volatility trigger.
            During cooldown, all orders on that symbol are rejected
            regardless of the current ATR.
        """
        self.max_atr_pct = max_atr_pct
        self.atr_period = atr_period
        self.cooldown = timedelta(minutes=cooldown_minutes)
        # symbol -> (atr, price) — most recent values.
        self._atr: dict[str, tuple[float, float]] = {}
        # symbol -> cooldown_until (UTC).
        self._cooldowns: dict[str, datetime] = {}

    async def update_atr(self, symbol: str, atr: float, price: float) -> None:
        """Push a fresh ATR/price snapshot for ``symbol``.

        Called by a bar-close subscriber (typically wired to
        ``atlas.ticks`` or a periodic candle aggregation job). ``atr`` and
        ``price`` must be in the same units.
        """
        self._atr[symbol] = (float(atr), float(price))
        if price > 0 and (atr / price) > self.max_atr_pct:
            self._cooldowns[symbol] = datetime.now(UTC) + self.cooldown
            _log.warning(
                "volatility_lock_triggered",
                symbol=symbol,
                atr_pct=atr / price,
                cap=self.max_atr_pct,
            )

    async def evaluate(self, ctx: OrderContext) -> None:
        """Reject the order if the symbol's ATR% is too high or it is in cooldown.

        Raises
        ------
        RiskLimitBreached
            If the symbol is currently in cooldown, or its latest ATR%
            exceeds ``max_atr_pct``.
        """
        now = datetime.now(UTC)

        # Cooldown check — supersedes the live ATR check.
        until = self._cooldowns.get(ctx.symbol)
        if until is not None:
            if now < until:
                raise RiskLimitBreached(
                    f"volatility_lock: {ctx.symbol} in cooldown until "
                    f"{until.isoformat()} (ATR spike)"
                )
            # Cooldown elapsed — clear it.
            self._cooldowns.pop(ctx.symbol, None)

        snapshot = self._atr.get(ctx.symbol)
        if snapshot is None:
            # No ATR data yet — fail open; let other rules decide.
            _log.debug("volatility_lock_no_data", symbol=ctx.symbol)
            return

        atr, price = snapshot
        if price <= 0:
            return
        atr_pct = atr / price
        if atr_pct > self.max_atr_pct:
            # Fresh spike — start cooldown and reject.
            self._cooldowns[ctx.symbol] = now + self.cooldown
            raise RiskLimitBreached(
                f"volatility_lock: {ctx.symbol} ATR%={atr_pct:.4f} (cap {self.max_atr_pct:.4f})"
            )

        _log.debug(
            "volatility_lock_ok",
            symbol=ctx.symbol,
            atr_pct=atr_pct,
            cap=self.max_atr_pct,
        )
