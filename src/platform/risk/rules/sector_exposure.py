"""Sector exposure rule — prevent over-concentration in one asset class.

Even if individual symbol exposure is bounded, a book can still be
over-exposed to a single sector (e.g. all money in metals). This rule
maps each symbol to a sector via a configurable lookup table and rejects
any new order that would push the sector's share of total notional
exposure above ``max_sector_pct``.

The default sector map covers the common retail-FX / CFD universe; users
can override the constructor argument to add custom sectors or remap
symbols. Symbols not present in any sector list are bucketed into
``"other"`` and grouped together.
"""

from __future__ import annotations

from collections import defaultdict
from platform.core.exceptions import RiskLimitBreached
from platform.core.logging import get_logger
from platform.db.models import Position
from platform.db.session import db_context
from platform.risk.engine import OrderContext, RiskRule

from sqlalchemy import select

_log = get_logger(__name__)


_DEFAULT_SECTORS: dict[str, list[str]] = {
    "metals": ["XAUUSD", "XAGUSD", "XAUEUR"],
    "fx": ["EURUSD", "GBPUSD", "USDJPY"],
    "crypto": ["BTCUSD", "ETHUSD"],
    "indices": ["US30", "NAS100", "SPX500"],
    "energy": ["XTIUSD", "XBRUSD"],
}


class SectorExposureRule(RiskRule):
    """Reject new orders that would push any sector's share above the cap."""

    name = "sector_exposure"

    def __init__(
        self,
        max_sector_pct: float = 0.50,
        sectors: dict[str, list[str]] | None = None,
    ) -> None:
        """Configure the rule.

        Parameters
        ----------
        max_sector_pct:
            Maximum share of total notional exposure that any single sector
            may occupy (e.g. ``0.50`` = a sector cannot exceed 50% of the
            total book).
        sectors:
            Mapping ``sector_name -> [symbol, ...]``. Defaults to the
            platform's standard sector map. Symbols not in any list are
            assigned to ``"other"``.
        """
        self.max_sector_pct = max_sector_pct
        self.sectors = (
            sectors if sectors is not None else {k: list(v) for k, v in _DEFAULT_SECTORS.items()}
        )
        # Reverse index: symbol -> sector
        self._symbol_to_sector: dict[str, str] = {}
        for sector, syms in self.sectors.items():
            for sym in syms:
                self._symbol_to_sector[sym] = sector

    def _sector_of(self, symbol: str) -> str:
        return self._symbol_to_sector.get(symbol, "other")

    async def evaluate(self, ctx: OrderContext) -> None:
        """Compute current sector exposure and reject if the cap would be breached.

        Raises
        ------
        RiskLimitBreached
            If the candidate symbol's sector share would exceed
            ``max_sector_pct`` after the new order is added.
        """
        async with db_context() as session:
            rows_stmt = select(Position.symbol, Position.volume, Position.current_price).where(
                Position.org_id == ctx.org_id,
                Position.status == "open",
            )
            rows = (await session.execute(rows_stmt)).all()

        sector_exposure: dict[str, float] = defaultdict(float)
        total = 0.0
        for sym, vol, price in rows:
            notional = float(vol) * float(price)
            sector_exposure[self._sector_of(sym)] += notional
            total += notional

        # Notional of the candidate order.
        price = ctx.price if ctx.price is not None else 0.0
        new_notional = ctx.volume * price
        candidate_sector = self._sector_of(ctx.symbol)
        new_sector_total = sector_exposure.get(candidate_sector, 0.0) + new_notional
        new_total = total + new_notional

        # Degenerate: no prior exposure and zero-priced order → skip.
        if new_total <= 0.0:
            return

        sector_share = new_sector_total / new_total
        if sector_share > self.max_sector_pct:
            raise RiskLimitBreached(
                f"sector_exposure: sector '{candidate_sector}' would be "
                f"{sector_share:.1%} of total (cap {self.max_sector_pct:.1%})"
            )

        _log.debug(
            "sector_exposure_ok",
            org_id=str(ctx.org_id),
            sector=candidate_sector,
            share=sector_share,
        )
