"""Correlation risk rule — block entries that would over-concentrate risk.

Diversification only works when positions are genuinely uncorrelated. This
rule maintains an in-memory Pearson correlation matrix between every pair
of symbols that currently has an open position, refreshed on each bar
close. Before opening a new position we check whether the candidate
symbol's correlation with any existing position exceeds the threshold.

The matrix is populated lazily: when the rule is asked to evaluate an
order, it pulls the most recent ``lookback_bars`` closed candles for the
candidate and for every open-position symbol, computes pairwise Pearson
correlations, and rejects if any exceeds ``max_correlation``.
"""

from __future__ import annotations

import math
from platform.core.exceptions import RiskLimitBreached
from platform.core.logging import get_logger
from platform.db.models import Candle, Position
from platform.db.session import db_context
from platform.risk.engine import OrderContext, RiskRule

from sqlalchemy import desc, select

_log = get_logger(__name__)


def correlation(series_a: list[float], series_b: list[float]) -> float:
    """Pearson correlation between two equal-length series; ``0.0`` for degenerate input."""
    n = min(len(series_a), len(series_b))
    if n < 2:
        return 0.0
    a = series_a[:n]
    b = series_b[:n]
    mean_a = sum(a) / n
    mean_b = sum(b) / n
    cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b, strict=False))
    var_a = sum((x - mean_a) ** 2 for x in a)
    var_b = sum((y - mean_b) ** 2 for y in b)
    denom = math.sqrt(var_a * var_b)
    if denom == 0.0:
        return 0.0
    return cov / denom


class CorrelationRiskRule(RiskRule):
    """Reject new entries whose correlation with existing positions is too high."""

    name = "correlation_risk"

    def __init__(
        self,
        max_correlation: float = 0.85,
        lookback_bars: int = 100,
    ) -> None:
        """Configure the rule.

        Parameters
        ----------
        max_correlation:
            Absolute Pearson correlation threshold above which a new entry
            is rejected (e.g. 0.85 = reject if candidate correlates >0.85
            with any existing open symbol).
        lookback_bars:
            Number of recent (closed) H1 candles used to compute the
            correlation matrix.
        """
        self.max_correlation = max_correlation
        self.lookback_bars = lookback_bars
        # In-memory cache: symbol -> list of close prices (most recent last).
        # Refreshed lazily on each evaluate call; cleared when positions change.
        self._matrix: dict[str, list[float]] = {}

    async def _load_closes(self, session, symbol: str) -> list[float]:
        stmt = (
            select(Candle.close)
            .where(Candle.symbol == symbol, Candle.timeframe == "H1", Candle.is_closed.is_(True))
            .order_by(desc(Candle.ts))
            .limit(self.lookback_bars)
        )
        rows = (await session.execute(stmt)).scalars().all()
        # Reverse so most-recent is at the end (chronological order).
        return [float(x) for x in reversed(rows)]

    async def evaluate(self, ctx: OrderContext) -> None:
        """Compute correlation between ``ctx.symbol`` and every open-position symbol.

        Raises
        ------
        RiskLimitBreached
            If the candidate symbol's correlation with any open-position
            symbol exceeds ``max_correlation``.
        """
        async with db_context() as session:
            open_symbols_stmt = (
                select(Position.symbol)
                .where(Position.org_id == ctx.org_id, Position.status == "open")
                .distinct()
            )
            open_symbols = {
                s
                for s in (await session.execute(open_symbols_stmt)).scalars().all()
                if s != ctx.symbol
            }
            if not open_symbols:
                return  # nothing to be correlated with

            candidate = await self._load_closes(session, ctx.symbol)
            if len(candidate) < 2:
                _log.debug("correlation_insufficient_data", symbol=ctx.symbol)
                return

            for sym in open_symbols:
                other = await self._load_closes(session, sym)
                if len(other) < 2:
                    continue
                corr = correlation(candidate, other)
                if abs(corr) > self.max_correlation:
                    raise RiskLimitBreached(
                        f"correlation_risk: {ctx.symbol} ↔ {sym} corr={corr:.3f} "
                        f"(threshold ±{self.max_correlation})"
                    )

        _log.debug("correlation_risk_ok", symbol=ctx.symbol, compared=len(open_symbols))
