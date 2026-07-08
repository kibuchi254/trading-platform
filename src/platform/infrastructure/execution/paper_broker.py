"""Paper broker adapter — in-memory order matching for backtests, paper trading, CI.

The `PaperBrokerAdapter` implements the `ExecutionAdapter` interface entirely
in memory: no sockets, no Redis, no MT5 terminal. It is suitable for:

  * Backtest engines that drive the platform with historical ticks
  * Paper trading in development environments
  * CI pipelines that must exercise the full PlaceOrder → ExecutionReport
    flow without an external broker

State managed by the adapter:

  * ``_orders``     — client_order_id → most recent ExecutionReport
  * ``_positions``  — broker_position_id → PositionSnapshot
  * ``_account``    — single AccountSnapshot, mark-to-market on every tick
  * ``_tick_cache`` — symbol → latest Tick (bid/ask)
  * ``_pending``    — broker_order_id → OrderRequest for limit/stop orders
                      awaiting trigger

Order matching semantics:

  * ``market``      — fills instantly at the current ask (buy) or bid (sell)
  * ``limit``       — accepted as pending; fills when the market price crosses
                      the limit price (buy: ask ≤ limit; sell: bid ≥ limit)
  * ``stop``        — accepted as pending; triggers when the market price
                      crosses the stop (buy: ask ≥ stop; sell: bid ≤ stop)
  * ``stop_limit``  — treated as a stop that fills at the trigger price
                      (simplified — no separate limit book)

Position update semantics (netting mode, one position per symbol):

  * Same-direction fill    → add to existing position (volume-weighted avg)
  * Opposite, smaller vol. → partial close, realize PnL
  * Opposite, larger vol.  → close existing & open reversed position for the
                              residual volume at the fill price
  * No existing position   → open a new position

Accounting (recomputed on every fill and tick):

  * Margin       = Σ (volume × open_price) / leverage
  * Equity       = balance + Σ unrealized_pnl
  * Free margin  = equity − margin
  * Realized PnL credited to balance on every partial / full close

Concurrency: an `asyncio.Lock` serializes state-mutating operations. The
internal `_xxx_locked` helpers perform synchronous state changes and may be
called recursively from within the lock without re-acquiring it. The tick
publish to the event bus happens *outside* the lock to avoid blocking other
operations during pub/sub fan-out.
"""
from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from platform.core.logging import get_logger
from platform.events.bus import get_event_bus
from platform.events.topics import Topic
from platform.infrastructure.execution.adapter_base import (
    AccountSnapshot,
    ExecutionAdapter,
    ExecutionReport,
    OrderRequest,
    PositionSnapshot,
)

_log = get_logger(__name__)


# ── Tick type ────────────────────────────────────────────────────────────────


@dataclass
class Tick:
    """Latest quote for a symbol held in the paper broker's tick cache."""

    symbol: str
    bid: float
    ask: float
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def mid(self) -> float:
        """Mid-market price — convenience for mark-to-market math."""
        return (self.bid + self.ask) / 2.0


# ── Adapter ──────────────────────────────────────────────────────────────────


class PaperBrokerAdapter(ExecutionAdapter):
    """In-memory broker simulation.

    All state lives in the adapter instance; there is no persistent storage.
    Call ``disconnect()`` to reset; the adapter can be reused afterwards with
    a fresh account balance equal to ``starting_balance``.

    Parameters
    ----------
    starting_balance:
        Initial cash balance for the simulated account. Defaults to $10,000.
    currency:
        Account currency code (default ``"USD"``).
    leverage:
        Account leverage used for margin calculations (default 100).
    seed:
        Optional RNG seed for deterministic ``generate_random_tick`` output.
        Useful for reproducible backtests / CI.
    """

    adapter_kind = "paper"

    def __init__(
        self,
        *,
        starting_balance: float = 10_000.0,
        currency: str = "USD",
        leverage: int = 100,
        seed: int | None = None,
    ) -> None:
        self._starting_balance: float = float(starting_balance)
        self._currency: str = currency
        self._leverage: int = int(leverage)
        self._rng: random.Random = random.Random(seed) if seed is not None else random.Random()

        self._orders: dict[str, ExecutionReport] = {}
        self._pending: dict[str, OrderRequest] = {}
        self._positions: dict[str, PositionSnapshot] = {}
        self._tick_cache: dict[str, Tick] = {}
        self._next_id: int = 0
        self._account: AccountSnapshot = self._fresh_account()

        self._lock: asyncio.Lock = asyncio.Lock()

    # ── Lifecycle ───────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """No-op — the paper broker is always 'connected'."""
        _log.info(
            "paper_broker_connected",
            starting_balance=self._starting_balance,
            currency=self._currency,
            leverage=self._leverage,
        )

    async def disconnect(self) -> None:
        """Clear all in-memory state.

        The adapter can be reused after this; the account is reset to the
        configured starting balance.
        """
        async with self._lock:
            self._orders.clear()
            self._pending.clear()
            self._positions.clear()
            self._tick_cache.clear()
            self._next_id = 0
            self._account = self._fresh_account()
        _log.info("paper_broker_disconnected")

    def _fresh_account(self) -> AccountSnapshot:
        return AccountSnapshot(
            balance=self._starting_balance,
            equity=self._starting_balance,
            margin=0.0,
            free_margin=self._starting_balance,
            currency=self._currency,
            leverage=self._leverage,
        )

    # ── Order placement ─────────────────────────────────────────────────────

    async def place_order(self, req: OrderRequest) -> ExecutionReport:
        """Place an order.

        Market orders fill immediately at the current tick (bid for sells,
        ask for buys). Limit / stop / stop_limit orders are stored as pending
        and will be triggered by subsequent ``update_ticks`` calls (or
        immediately if the current market already crosses the order price).

        Returns an :class:`ExecutionReport` with status ``filled`` for market
        orders, ``accepted`` for pending limit/stop orders, or ``rejected``
        if validation fails (invalid volume, no market data, etc.).
        """
        async with self._lock:
            return self._place_order_locked(req)

    def _place_order_locked(self, req: OrderRequest) -> ExecutionReport:
        now = datetime.now(timezone.utc)
        broker_order_id = self._generate_id("PBO")

        if req.volume <= 0:
            return self._reject(req, broker_order_id, "invalid_volume", now)

        if req.order_type == "market":
            return self._fill_market_locked(req, broker_order_id, now)

        if req.order_type in ("limit", "stop", "stop_limit"):
            if req.price is None:
                return self._reject(req, broker_order_id, "price_required", now)
            report = ExecutionReport(
                client_order_id=req.client_order_id,
                broker_order_id=broker_order_id,
                status="accepted",
                filled_volume=0.0,
                avg_price=None,
                executed_at=now,
            )
            self._orders[req.client_order_id] = report
            self._pending[broker_order_id] = req
            _log.info(
                "paper_order_pending",
                client_order_id=req.client_order_id,
                broker_order_id=broker_order_id,
                order_type=req.order_type,
                price=req.price,
                symbol=req.symbol,
                side=req.side,
                volume=req.volume,
            )
            # Try an immediate trigger in case the current market already crosses.
            # ``_try_trigger_locked`` overwrites the report in ``self._orders``
            # if it fires.
            self._try_trigger_locked(broker_order_id)
            return self._orders[req.client_order_id]

        return self._reject(req, broker_order_id, f"unsupported_order_type:{req.order_type}", now)

    def _fill_market_locked(
        self, req: OrderRequest, broker_order_id: str, now: datetime
    ) -> ExecutionReport:
        tick = self._tick_cache.get(req.symbol)
        if tick is None:
            return self._reject(req, broker_order_id, "no_market_data", now)
        fill_price = tick.ask if req.side == "buy" else tick.bid
        broker_execution_id = self._generate_id("PBX")
        self._apply_fill_locked(req, fill_price, req.volume)
        report = ExecutionReport(
            client_order_id=req.client_order_id,
            broker_order_id=broker_order_id,
            broker_execution_id=broker_execution_id,
            status="filled",
            filled_volume=req.volume,
            avg_price=fill_price,
            executed_at=now,
        )
        self._orders[req.client_order_id] = report
        _log.info(
            "paper_order_filled",
            client_order_id=req.client_order_id,
            broker_order_id=broker_order_id,
            side=req.side,
            symbol=req.symbol,
            volume=req.volume,
            price=fill_price,
        )
        return report

    def _reject(
        self,
        req: OrderRequest,
        broker_order_id: str | None,
        reason: str,
        now: datetime,
    ) -> ExecutionReport:
        report = ExecutionReport(
            client_order_id=req.client_order_id,
            broker_order_id=broker_order_id,
            status="rejected",
            filled_volume=0.0,
            rejection_reason=reason,
            executed_at=now,
        )
        self._orders[req.client_order_id] = report
        _log.warning(
            "paper_order_rejected",
            client_order_id=req.client_order_id,
            broker_order_id=broker_order_id,
            reason=reason,
        )
        return report

    # ── Pending order triggering ────────────────────────────────────────────

    def _try_trigger_locked(self, broker_order_id: str) -> bool:
        """Check whether a pending order should trigger at the current tick.

        Returns ``True`` if the order was filled (and removed from the
        pending book). Returns ``False`` if it remains pending or has
        already been cancelled / filled.
        """
        req = self._pending.get(broker_order_id)
        if req is None:
            return False
        tick = self._tick_cache.get(req.symbol)
        if tick is None:
            return False

        triggered = False
        if req.order_type == "limit":
            if req.side == "buy" and tick.ask <= req.price:
                triggered = True
            elif req.side == "sell" and tick.bid >= req.price:
                triggered = True
        elif req.order_type in ("stop", "stop_limit"):
            if req.side == "buy" and tick.ask >= req.price:
                triggered = True
            elif req.side == "sell" and tick.bid <= req.price:
                triggered = True

        if not triggered:
            return False

        # For limit orders, fill at the limit price (price improvement
        # possible — but the broker model here is conservative). For stop
        # orders, fill at the current ask (buy) / bid (sell).
        if req.order_type == "limit":
            fill_price = req.price
        else:  # stop / stop_limit
            fill_price = tick.ask if req.side == "buy" else tick.bid

        now = datetime.now(timezone.utc)
        broker_execution_id = self._generate_id("PBX")
        self._apply_fill_locked(req, fill_price, req.volume)
        report = ExecutionReport(
            client_order_id=req.client_order_id,
            broker_order_id=broker_order_id,
            broker_execution_id=broker_execution_id,
            status="filled",
            filled_volume=req.volume,
            avg_price=fill_price,
            executed_at=now,
        )
        self._orders[req.client_order_id] = report
        self._pending.pop(broker_order_id, None)
        _log.info(
            "paper_pending_filled",
            client_order_id=req.client_order_id,
            broker_order_id=broker_order_id,
            order_type=req.order_type,
            price=fill_price,
        )
        return True

    # ── Position accounting ─────────────────────────────────────────────────

    def _apply_fill_locked(self, req: OrderRequest, fill_price: float, volume: float) -> None:
        """Apply a fill to the position set: open / increase / close / reverse.

        Realized PnL is credited to the account balance immediately on every
        partial or full close. Account metrics (margin, equity, free_margin)
        are recomputed at the end.
        """
        existing = next(
            (p for p in self._positions.values() if p.symbol == req.symbol),
            None,
        )

        if existing is None:
            self._open_position_locked(req, fill_price, volume)
        elif existing.side == req.side:
            # Increase position — volume-weighted average open price
            new_volume = existing.volume + volume
            new_open = (existing.open_price * existing.volume + fill_price * volume) / new_volume
            existing.volume = new_volume
            existing.open_price = new_open
            if req.stop_loss is not None:
                existing.stop_loss = req.stop_loss
            if req.take_profit is not None:
                existing.take_profit = req.take_profit
            self._mark_position(existing, fill_price)
            _log.info(
                "paper_position_increased",
                broker_position_id=existing.broker_position_id,
                added_volume=volume,
                new_volume=new_volume,
                new_open=new_open,
            )
        else:
            # Opposite direction — reduce / close / reverse
            close_volume = min(volume, existing.volume)
            realized = self._realized_pnl(existing.side, existing.open_price, fill_price, close_volume)
            self._account.balance += realized

            remaining = volume - close_volume
            if remaining <= 0:
                # Partial or full close
                if close_volume >= existing.volume:
                    self._positions.pop(existing.broker_position_id, None)
                    _log.info(
                        "paper_position_closed",
                        broker_position_id=existing.broker_position_id,
                        realized_pnl=realized,
                    )
                else:
                    existing.volume -= close_volume
                    self._mark_position(existing, fill_price)
                    _log.info(
                        "paper_position_partial_close",
                        broker_position_id=existing.broker_position_id,
                        closed_volume=close_volume,
                        remaining_volume=existing.volume,
                        realized_pnl=realized,
                    )
            else:
                # Reversal — close existing, open new in opposite direction
                self._positions.pop(existing.broker_position_id, None)
                _log.info(
                    "paper_position_reversed",
                    broker_position_id=existing.broker_position_id,
                    realized_pnl=realized,
                    new_side=req.side,
                    new_volume=remaining,
                )
                self._open_position_locked(req, fill_price, remaining)

        self._recompute_account()

    def _open_position_locked(self, req: OrderRequest, fill_price: float, volume: float) -> str:
        broker_position_id = self._generate_id("PBP")
        now = datetime.now(timezone.utc)
        pos = PositionSnapshot(
            broker_position_id=broker_position_id,
            symbol=req.symbol,
            side=req.side,
            volume=volume,
            open_price=fill_price,
            current_price=fill_price,
            stop_loss=req.stop_loss,
            take_profit=req.take_profit,
            swap=0.0,
            unrealized_pnl=0.0,
            opened_at=now,
        )
        self._positions[broker_position_id] = pos
        _log.info(
            "paper_position_opened",
            broker_position_id=broker_position_id,
            symbol=req.symbol,
            side=req.side,
            volume=volume,
            open_price=fill_price,
        )
        return broker_position_id

    @staticmethod
    def _realized_pnl(side: str, open_price: float, close_price: float, volume: float) -> float:
        """Realized PnL for closing `volume` units of a position opened at
        `open_price` and closed at `close_price`. Positive for profit."""
        if side == "buy":
            return (close_price - open_price) * volume
        return (open_price - close_price) * volume

    @staticmethod
    def _mark_position(pos: PositionSnapshot, mark_price: float) -> None:
        """Update a position's current_price and unrealized_pnl given a mark."""
        pos.current_price = mark_price
        if pos.side == "buy":
            pos.unrealized_pnl = (mark_price - pos.open_price) * pos.volume
        else:
            pos.unrealized_pnl = (pos.open_price - mark_price) * pos.volume

    def _recompute_account(self) -> None:
        """Recompute equity, margin, free_margin from current positions.

        Balance is the only input that is *not* derived from positions — it
        changes only when PnL is realized.
        """
        unrealized = sum(p.unrealized_pnl for p in self._positions.values())
        margin = sum(p.volume * p.open_price / self._leverage for p in self._positions.values())
        equity = self._account.balance + unrealized
        self._account.equity = equity
        self._account.margin = margin
        self._account.free_margin = equity - margin

    # ── Cancel / close / modify ─────────────────────────────────────────────

    async def cancel_order(self, broker_order_id: str) -> ExecutionReport:
        """Cancel a pending limit/stop order. Returns a cancelled report.

        If the order is unknown or already filled, returns a rejected report
        with a descriptive ``rejection_reason``.
        """
        async with self._lock:
            return self._cancel_order_locked(broker_order_id)

    def _cancel_order_locked(self, broker_order_id: str) -> ExecutionReport:
        now = datetime.now(timezone.utc)
        req = self._pending.pop(broker_order_id, None)
        if req is not None:
            report = ExecutionReport(
                client_order_id=req.client_order_id,
                broker_order_id=broker_order_id,
                status="cancelled",
                filled_volume=0.0,
                executed_at=now,
            )
            self._orders[req.client_order_id] = report
            _log.info("paper_order_cancelled", broker_order_id=broker_order_id)
            return report

        # Not pending — see if we know about it at all
        for cid, rpt in self._orders.items():
            if rpt.broker_order_id == broker_order_id:
                return ExecutionReport(
                    client_order_id=cid,
                    broker_order_id=broker_order_id,
                    status="rejected",
                    rejection_reason="order_not_pending",
                    executed_at=now,
                )
        return ExecutionReport(
            client_order_id="",
            broker_order_id=broker_order_id,
            status="rejected",
            rejection_reason="order_not_found",
            executed_at=now,
        )

    async def close_position(
        self, broker_position_id: str, volume: float | None = None
    ) -> ExecutionReport:
        """Close (or partially close) a position at the current market price.

        Realized PnL is credited to the account balance immediately. If
        ``volume`` is ``None``, the entire position is closed.

        Returns a rejected report if the position is unknown, the symbol has
        no market data, or the requested close volume is invalid.
        """
        async with self._lock:
            return self._close_position_locked(broker_position_id, volume, reason="manual")

    def _close_position_locked(
        self,
        broker_position_id: str,
        volume: float | None,
        *,
        reason: str = "manual",
    ) -> ExecutionReport:
        now = datetime.now(timezone.utc)
        pos = self._positions.get(broker_position_id)
        if pos is None:
            return ExecutionReport(
                client_order_id="",
                broker_order_id=None,
                status="rejected",
                rejection_reason="position_not_found",
                executed_at=now,
            )
        tick = self._tick_cache.get(pos.symbol)
        if tick is None:
            return ExecutionReport(
                client_order_id="",
                broker_order_id=None,
                status="rejected",
                rejection_reason="no_market_data",
                executed_at=now,
            )

        close_price = tick.bid if pos.side == "buy" else tick.ask
        close_volume = volume if volume is not None else pos.volume
        if close_volume <= 0 or close_volume > pos.volume + 1e-12:
            return ExecutionReport(
                client_order_id="",
                broker_order_id=None,
                status="rejected",
                rejection_reason="invalid_close_volume",
                executed_at=now,
            )

        realized = self._realized_pnl(pos.side, pos.open_price, close_price, close_volume)
        self._account.balance += realized

        broker_execution_id = self._generate_id("PBX")
        broker_order_id = self._generate_id("PBO")
        client_order_id = f"close-{broker_position_id}"

        if close_volume >= pos.volume - 1e-12:
            self._positions.pop(broker_position_id, None)
            _log.info(
                "paper_position_closed",
                broker_position_id=broker_position_id,
                realized_pnl=realized,
                reason=reason,
            )
        else:
            pos.volume -= close_volume
            self._mark_position(pos, close_price)
            _log.info(
                "paper_position_partial_close",
                broker_position_id=broker_position_id,
                closed_volume=close_volume,
                remaining_volume=pos.volume,
                realized_pnl=realized,
                reason=reason,
            )

        self._recompute_account()
        report = ExecutionReport(
            client_order_id=client_order_id,
            broker_order_id=broker_order_id,
            broker_execution_id=broker_execution_id,
            status="filled",
            filled_volume=close_volume,
            avg_price=close_price,
            executed_at=now,
        )
        self._orders[client_order_id] = report
        return report

    async def modify_position(
        self,
        broker_position_id: str,
        *,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> ExecutionReport:
        """Modify a position's stop-loss and/or take-profit.

        Only the fields that are not ``None`` are updated. Returns an
        ``accepted`` report on success, or a ``rejected`` report if the
        position is unknown.
        """
        async with self._lock:
            return self._modify_position_locked(broker_position_id, stop_loss, take_profit)

    def _modify_position_locked(
        self,
        broker_position_id: str,
        stop_loss: float | None,
        take_profit: float | None,
    ) -> ExecutionReport:
        now = datetime.now(timezone.utc)
        pos = self._positions.get(broker_position_id)
        if pos is None:
            return ExecutionReport(
                client_order_id="",
                broker_order_id=None,
                status="rejected",
                rejection_reason="position_not_found",
                executed_at=now,
            )
        if stop_loss is not None:
            pos.stop_loss = stop_loss
        if take_profit is not None:
            pos.take_profit = take_profit
        broker_order_id = self._generate_id("PBO")
        client_order_id = f"modify-{broker_position_id}"
        report = ExecutionReport(
            client_order_id=client_order_id,
            broker_order_id=broker_order_id,
            status="accepted",
            filled_volume=pos.volume,
            avg_price=pos.open_price,
            executed_at=now,
        )
        self._orders[client_order_id] = report
        _log.info(
            "paper_position_modified",
            broker_position_id=broker_position_id,
            stop_loss=pos.stop_loss,
            take_profit=pos.take_profit,
        )
        return report

    # ── Sync ────────────────────────────────────────────────────────────────

    async def sync_positions(self) -> list[PositionSnapshot]:
        """Return a list of all currently-open positions.

        The returned snapshots are *references* into the internal state —
        callers should treat them as read-only.
        """
        async with self._lock:
            return [p.model_copy() for p in self._positions.values()]

    async def sync_account(self) -> AccountSnapshot:
        """Return a copy of the current account snapshot, freshly marked."""
        async with self._lock:
            self._recompute_account()
            return self._account.model_copy()

    async def subscribe_ticks(self, symbols: list[str]) -> None:
        """No-op — the paper broker does not subscribe to external feeds.

        Tick data is provided via :meth:`update_ticks` (for backtests driven
        by an external tick source) or :meth:`generate_random_tick` (for
        randomized testing).
        """
        _log.debug("paper_subscribe_ticks_noop", symbols=symbols)

    async def get_history(
        self,
        *,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        """Not implemented — historical bars are loaded from the DB / market
        data store, not from the paper broker."""
        return []

    # ── Tick updates & mark-to-market ───────────────────────────────────────

    async def update_ticks(self, symbol: str, bid: float, ask: float) -> None:
        """Update the latest tick for a symbol.

        Side effects (in order, under the lock):

          1. Tick cache is updated.
          2. All pending orders for this symbol are checked for trigger
             conditions; triggering orders fill immediately at the limit /
             stop price (or the current market for stop orders).
          3. All open positions for this symbol are marked-to-market at the
             new bid (for longs) / ask (for shorts). Stop-loss and
             take-profit levels are checked; positions are auto-closed if
             either is hit.
          4. Account equity / margin / free_margin are recomputed.

        After releasing the lock, the tick is published on the
        ``atlas.ticks`` event bus topic so downstream subscribers (strategies,
        market data engine, AI modules) see the update.
        """
        async with self._lock:
            tick = self._update_ticks_locked(symbol, bid, ask)

        bus = get_event_bus()
        await bus.publish(
            Topic.TICKS,
            {
                "symbol": symbol,
                "bid": bid,
                "ask": ask,
                "last": tick.mid,
                "ts": tick.ts.isoformat(),
                "source": "paper",
            },
        )

    def _update_ticks_locked(self, symbol: str, bid: float, ask: float) -> Tick:
        now = datetime.now(timezone.utc)
        tick = Tick(symbol=symbol, bid=bid, ask=ask, ts=now)
        self._tick_cache[symbol] = tick

        # 1. Trigger any pending orders whose price has been crossed.
        for broker_order_id in list(self._pending.keys()):
            self._try_trigger_locked(broker_order_id)

        # 2. Mark-to-market & check SL/TP for every open position on this symbol.
        for pos in list(self._positions.values()):
            if pos.symbol != symbol:
                continue
            mark_price = bid if pos.side == "buy" else ask
            self._mark_position(pos, mark_price)

            should_close = False
            reason = ""
            if pos.stop_loss is not None:
                if pos.side == "buy" and bid <= pos.stop_loss:
                    should_close, reason = True, "stop_loss"
                elif pos.side == "sell" and ask >= pos.stop_loss:
                    should_close, reason = True, "stop_loss"
            if not should_close and pos.take_profit is not None:
                if pos.side == "buy" and bid >= pos.take_profit:
                    should_close, reason = True, "take_profit"
                elif pos.side == "sell" and ask <= pos.take_profit:
                    should_close, reason = True, "take_profit"

            if should_close:
                # ``_close_position_locked`` mutates ``self._positions``; we
                # are iterating over a snapshot copy so this is safe.
                self._close_position_locked(pos.broker_position_id, None, reason=reason)

        # 3. Recompute account metrics after all marks and fills.
        self._recompute_account()
        return tick

    async def generate_random_tick(self, symbol: str) -> tuple[float, float]:
        """Generate a random-walk tick around the last known price.

        Uses a Gaussian-free uniform step of ±0.1% of the last mid price
        (or 1.0000 if no prior tick exists for the symbol). A 1-pip spread
        is applied symmetrically around the new mid.

        Returns the ``(bid, ask)`` tuple that was generated and applied.
        """
        last = self._tick_cache.get(symbol)
        mid = last.mid if last is not None else 1.0000
        # ±0.1% uniform random walk
        step = mid * 0.001 * (self._rng.random() * 2.0 - 1.0)
        new_mid = max(mid + step, 0.0001)
        spread = new_mid * 0.0001  # 1 pip
        bid = round(new_mid - spread / 2.0, 6)
        ask = round(new_mid + spread / 2.0, 6)
        await self.update_ticks(symbol, bid, ask)
        return bid, ask

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _generate_id(self, prefix: str) -> str:
        """Generate a monotonically-increasing broker-side identifier.

        The prefix identifies the entity kind:
          * ``PBO`` — Paper Broker Order
          * ``PBP`` — Paper Broker Position
          * ``PBX`` — Paper Broker eXecution
        """
        self._next_id += 1
        return f"{prefix}-{self._next_id:08d}"


__all__ = ["PaperBrokerAdapter", "Tick"]
