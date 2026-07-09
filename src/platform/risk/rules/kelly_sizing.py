"""Kelly sizing rule — suggest a position size based on historical edge.

Unlike every other rule in this pack, :class:`KellySizingRule` **does not
reject** orders. Instead it computes a Kelly-optimal position size based on
the strategy's historical win-rate and payoff ratio, applies a sanity cap,
and stores the suggestion in an in-memory dict keyed by
``(terminal_id, symbol)``. The downstream order router is free to use (or
ignore) the suggestion.

Kelly fraction: ``f* = (p * b - q) / b`` where ``p`` = win-rate,
``q = 1 - p``, ``b = avg_win / avg_loss``. We cap ``f*`` at
``cap_fraction`` (default 25%) to avoid the well-known problem of
full-Kelly being pathologically sensitive to estimation error.

If fewer than ``min_trades_for_stats`` trades exist for the strategy,
we fall back to ``default_win_rate`` and ``default_payoff``.
"""

from __future__ import annotations

from platform.core.logging import get_logger
from platform.db.models import Trade
from platform.db.session import db_context
from platform.risk.engine import OrderContext, RiskRule
from uuid import UUID

from sqlalchemy import desc, select

_log = get_logger(__name__)


def kelly(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Compute the Kelly fraction for a binary-outcome strategy.

    ``win_rate`` is the probability ``p ∈ (0, 1)``; ``avg_win`` and
    ``avg_loss`` are positive magnitudes. Returns the fraction ``f*``
    clamped to ``[0, 1]``; ``0.0`` for degenerate inputs (no edge,
    zero loss, etc.).
    """
    if avg_loss <= 0 or win_rate <= 0 or win_rate >= 1:
        return 0.0
    b = avg_win / avg_loss
    if b <= 0:
        return 0.0
    p = win_rate
    q = 1.0 - p
    f = (p * b - q) / b
    return max(0.0, min(1.0, f))


class KellySizingRule(RiskRule):
    """Compute and cache a Kelly-optimal position size suggestion per order."""

    name = "kelly_sizing"

    def __init__(
        self,
        cap_fraction: float = 0.25,
        min_trades_for_stats: int = 20,
        default_win_rate: float = 0.5,
        default_payoff: float = 1.5,
    ) -> None:
        """Configure the rule.

        ``cap_fraction`` is the maximum Kelly fraction suggested
        (quarter-Kelly by default). Below ``min_trades_for_stats`` history
        the rule falls back to ``default_win_rate`` / ``default_payoff``.
        """
        self.cap_fraction = cap_fraction
        self.min_trades_for_stats = min_trades_for_stats
        self.default_win_rate = default_win_rate
        self.default_payoff = default_payoff
        # (terminal_id, symbol) -> suggested_volume
        self._suggestions: dict[tuple[str, str], float] = {}

    def get_suggestion(self, terminal_id: str, symbol: str) -> float | None:
        """Return the most recently suggested volume for ``(terminal_id, symbol)``, or ``None``."""
        return self._suggestions.get((terminal_id, symbol))

    async def _compute_stats(self, session, strategy_id: UUID) -> tuple[int, float, float, float]:
        """Return ``(n_trades, win_rate, avg_win, avg_loss)`` for the strategy."""
        stmt = (
            select(Trade.pnl)
            .where(Trade.strategy_id == strategy_id)
            .order_by(desc(Trade.closed_at))
            .limit(500)  # rolling window of most recent 500 trades
        )
        pnls = [float(p) for p in (await session.execute(stmt)).scalars().all()]
        n = len(pnls)
        if n == 0:
            return 0, self.default_win_rate, 0.0, 0.0
        wins = [p for p in pnls if p > 0]
        losses = [-p for p in pnls if p < 0]  # store as positive magnitudes
        win_rate = len(wins) / n
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        return n, win_rate, avg_win, avg_loss

    async def evaluate(self, ctx: OrderContext) -> None:
        """Compute Kelly fraction, cap it, store the suggested volume.

        Never raises — always succeeds and updates the internal cache.
        ``ctx.meta`` (optional) may carry ``strategy_id`` (UUID),
        ``account_equity``, and ``stop_distance`` for richer sizing.
        """
        meta = getattr(ctx, "meta", None) or {}
        strategy_id = meta.get("strategy_id") if isinstance(meta, dict) else None
        account_equity = float(meta.get("account_equity", 0.0)) if isinstance(meta, dict) else 0.0

        win_rate = self.default_win_rate
        avg_win = self.default_payoff  # paired with avg_loss=1 below
        avg_loss = 1.0

        if strategy_id is not None:
            async with db_context() as session:
                n, wr, aw, al = await self._compute_stats(session, strategy_id)
            if n >= self.min_trades_for_stats and al > 0:
                win_rate, avg_win, avg_loss = wr, aw, al
            elif n > 0:
                _log.debug(
                    "kelly_insufficient_history",
                    strategy_id=str(strategy_id),
                    n_trades=n,
                    required=self.min_trades_for_stats,
                )

        f = kelly(win_rate, avg_win, avg_loss)
        f_capped = min(f, self.cap_fraction)

        # If caller supplied equity + stop_distance via meta: volume = (equity * f) / stop.
        # Otherwise scale the requested volume by the capped Kelly fraction.
        suggested_volume: float
        if isinstance(meta, dict) and account_equity > 0 and meta.get("stop_distance"):
            try:
                sd = float(meta["stop_distance"])
                suggested_volume = (
                    (account_equity * f_capped) / sd if sd > 0 else ctx.volume * f_capped
                )
            except (TypeError, ValueError):
                suggested_volume = ctx.volume * f_capped
        else:
            suggested_volume = ctx.volume * f_capped

        self._suggestions[(ctx.terminal_id, ctx.symbol)] = suggested_volume
        _log.debug(
            "kelly_suggestion",
            terminal_id=ctx.terminal_id,
            symbol=ctx.symbol,
            win_rate=win_rate,
            kelly_f=f,
            capped_f=f_capped,
            suggested_volume=suggested_volume,
        )
