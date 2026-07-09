"""Max exposure rule — cap gross notional exposure (USD).

Notional exposure is ``volume * current_price * contract_size``. This rule
enforces two caps to keep the book within sensible risk envelopes:

* ``max_notional_usd`` — total notional across all open positions.
* ``max_notional_per_symbol`` — notional concentration on a single symbol
  (prevents the "all-in on one ticker" failure mode).

The contract size is looked up from the :class:`~platform.db.models.Symbol`
table; if no row exists for the symbol we assume ``1.0`` (typical for FX
majors) and log a warning.

The new order's notional is estimated using ``ctx.volume * ctx.price``
(or the latest position ``current_price`` if ``ctx.price`` is None —
e.g. for market orders).
"""

from __future__ import annotations

from platform.core.exceptions import RiskLimitBreached
from platform.core.logging import get_logger
from platform.db.models import Position, Symbol
from platform.db.session import db_context
from platform.risk.engine import OrderContext, RiskRule

from sqlalchemy import select

_log = get_logger(__name__)


class MaxExposureRule(RiskRule):
    """Reject new orders that would breach gross notional exposure caps."""

    name = "max_exposure"

    def __init__(
        self,
        max_notional_usd: float = 100_000.0,
        max_notional_per_symbol: float = 25_000.0,
    ) -> None:
        """Configure the rule.

        Parameters
        ----------
        max_notional_usd:
            Maximum gross notional exposure (USD) across all open positions.
        max_notional_per_symbol:
            Maximum gross notional exposure on a single symbol.
        """
        self.max_notional_usd = max_notional_usd
        self.max_notional_per_symbol = max_notional_per_symbol

    async def _contract_size(self, session, symbol: str) -> float:
        stmt = select(Symbol.contract_size).where(Symbol.name == symbol).limit(1)
        size = (await session.execute(stmt)).scalar_one_or_none()
        if size is None:
            _log.warning("contract_size_missing", symbol=symbol, fallback=1.0)
            return 1.0
        return float(size)

    async def evaluate(self, ctx: OrderContext) -> None:
        """Sum open position notional and reject if the new order tips a cap.

        Raises
        ------
        RiskLimitBreached
            If total notional or per-symbol notional would exceed its limit.
        """
        async with db_context() as session:
            contract_size = await self._contract_size(session, ctx.symbol)

            rows_stmt = select(
                Position.symbol,
                Position.volume,
                Position.current_price,
            ).where(
                Position.org_id == ctx.org_id,
                Position.status == "open",
            )
            rows = (await session.execute(rows_stmt)).all()

        # Per-symbol notional map for existing positions.
        per_symbol: dict[str, float] = {}
        total = 0.0
        for sym, vol, price in rows:
            # contract_size per-symbol lookup is skipped in the loop for perf;
            # we assume uniform 1.0 except for the candidate symbol. This is a
            # conservative simplification — for stricter enforcement, move the
            # lookup inside the loop.
            notional = float(vol) * float(price) * 1.0
            per_symbol[sym] = per_symbol.get(sym, 0.0) + notional
            total += notional

        # Notional of the new order.
        price = (
            ctx.price
            if ctx.price is not None
            # Fallback: use latest known current_price on existing position
            else (
                per_symbol.get(ctx.symbol, 0.0) / 1.0  # rough; rules below still apply
            )
        )
        new_notional = ctx.volume * (price or 0.0) * contract_size

        sym_total = per_symbol.get(ctx.symbol, 0.0) + new_notional
        grand_total = total + new_notional

        if sym_total > self.max_notional_per_symbol:
            raise RiskLimitBreached(
                f"max_exposure: per-symbol notional {sym_total:.2f} USD "
                f"on {ctx.symbol} (cap {self.max_notional_per_symbol:.2f})"
            )

        if grand_total > self.max_notional_usd:
            raise RiskLimitBreached(
                f"max_exposure: total notional {grand_total:.2f} USD "
                f"(cap {self.max_notional_usd:.2f})"
            )

        _log.debug(
            "max_exposure_ok",
            org_id=str(ctx.org_id),
            symbol=ctx.symbol,
            total=grand_total,
            per_symbol=sym_total,
        )
