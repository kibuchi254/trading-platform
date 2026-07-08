"""Position limit rule — cap the number of concurrent positions.

A trader's worst enemy is over-trading. This rule enforces two hard caps:

* ``max_positions_per_symbol`` — no more than N open positions on a single
  symbol (e.g. prevents pyramiding into a single ticker).
* ``max_positions_total`` — no more than N open positions across the entire
  org. Beyond this, the trader is over-diversified / over-leveraged and new
  entries are blocked until something closes.

The check is performed against the ``positions`` table filtered by
``org_id`` and ``status='open'``. The incoming order is assumed to open a
new position; closing orders (which the bridge tags via the order type)
should bypass this rule at the engine level.
"""
from __future__ import annotations

from sqlalchemy import func, select

from platform.core.exceptions import RiskLimitBreached
from platform.core.logging import get_logger
from platform.db.models import Position
from platform.db.session import db_context
from platform.risk.engine import OrderContext, RiskRule

_log = get_logger(__name__)


class PositionLimitRule(RiskRule):
    """Reject new orders that would breach per-symbol or total position limits."""

    name = "position_limit"

    def __init__(
        self,
        max_positions_per_symbol: int = 5,
        max_positions_total: int = 50,
    ) -> None:
        """Configure the rule.

        Parameters
        ----------
        max_positions_per_symbol:
            Hard cap on concurrent open positions for a single symbol.
        max_positions_total:
            Hard cap on concurrent open positions across the entire org.
        """
        self.max_positions_per_symbol = max_positions_per_symbol
        self.max_positions_total = max_positions_total

    async def evaluate(self, ctx: OrderContext) -> None:
        """Count open positions for the org and reject if a cap would be breached.

        Raises
        ------
        RiskLimitBreached
            If either the per-symbol count or the total count is already at
            its limit (the new order would push it over).
        """
        async with db_context() as session:
            # Total open positions for this org.
            total_stmt = (
                select(func.count(Position.id))
                .where(Position.org_id == ctx.org_id, Position.status == "open")
            )
            total_open = (await session.execute(total_stmt)).scalar_one()

            # Open positions for this specific symbol.
            sym_stmt = (
                select(func.count(Position.id))
                .where(
                    Position.org_id == ctx.org_id,
                    Position.status == "open",
                    Position.symbol == ctx.symbol,
                )
            )
            sym_open = (await session.execute(sym_stmt)).scalar_one()

        # The incoming order would add one more position to both counts
        # (we assume it opens a new position — closing flow is handled upstream).
        if sym_open + 1 > self.max_positions_per_symbol:
            raise RiskLimitBreached(
                f"position_limit: {sym_open} open positions on {ctx.symbol} "
                f"(cap {self.max_positions_per_symbol})"
            )

        if total_open + 1 > self.max_positions_total:
            raise RiskLimitBreached(
                f"position_limit: {total_open} total open positions "
                f"(cap {self.max_positions_total})"
            )

        _log.debug(
            "position_limit_ok",
            org_id=str(ctx.org_id),
            symbol=ctx.symbol,
            total_open=total_open,
            sym_open=sym_open,
        )
