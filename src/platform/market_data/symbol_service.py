"""Symbol service — symbol metadata management with lazy in-memory caching.

Wraps CRUD operations on the ``symbols`` table behind a small read-through
cache. The cache is keyed by ``name`` (e.g. ``"EURUSD"``) and is loaded
lazily — first access for a name hits the DB and warms the cache; subsequent
accesses return the cached ORM instance.

When a terminal registers (or re-registers) it advertises the list of
symbols it can trade; ``update_from_terminal`` syncs that list into the
``symbols`` table, upserting rows for any new names and refreshing metadata
(digits, volume_min, …) for known ones.
"""

from __future__ import annotations

from platform.core.logging import get_logger
from platform.db.models import Symbol, Terminal
from platform.db.session import db_context
from typing import Any

from sqlalchemy import select

_log = get_logger(__name__)


class SymbolService:
    """Symbol metadata CRUD + lazy in-memory cache."""

    def __init__(self) -> None:
        # name -> detached Symbol ORM instance. Detached so callers can use
        # them outside the session that produced them. Treat as read-only.
        self._cache: dict[str, Symbol] = {}

    # ── Public API ──────────────────────────────────────────────────────────

    async def get_or_create(self, name: str, **kwargs: Any) -> Symbol:
        """Upsert a symbol by name. Returns the persisted (and cached) instance.

        Optional ``kwargs`` map directly to ``Symbol`` column names —
        ``category``, ``digits``, ``contract_size``, ``volume_min``,
        ``volume_step``, ``volume_max``, ``description``, ``broker_id``,
        ``org_id``. Any kwargs not provided default to the model's defaults
        on insert, or are left untouched on update.
        """
        async with db_context() as db:
            stmt = select(Symbol).where(Symbol.name == name)
            existing = (await db.execute(stmt)).scalar_one_or_none()
            if existing is None:
                row = Symbol(name=name, **kwargs)
                db.add(row)
                await db.commit()
                await db.refresh(row)
                db.expunge(row)
                self._cache[name] = row
                _log.info("symbol_created", name=name, category=kwargs.get("category"))
                return row

            # Update — only overwrite fields that were explicitly supplied.
            dirty = False
            for k, v in kwargs.items():
                if hasattr(existing, k) and getattr(existing, k) != v:
                    setattr(existing, k, v)
                    dirty = True
            if dirty:
                await db.commit()
                await db.refresh(existing)
            db.expunge(existing)
            self._cache[name] = existing
            return existing

    async def get(self, name: str) -> Symbol | None:
        """Fetch a symbol by name. Returns the cached instance if warm.

        Cache miss → DB hit → cache fill. Returns ``None`` if the symbol does
        not exist.
        """
        cached = self._cache.get(name)
        if cached is not None:
            return cached
        async with db_context() as db:
            stmt = select(Symbol).where(Symbol.name == name)
            row = (await db.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            db.expunge(row)
            self._cache[name] = row
            return row

    async def list_all(self, category: str | None = None) -> list[Symbol]:
        """List symbols, optionally filtered by ``category`` (e.g. ``"fx"``).

        The result is **not** cached — list queries are typically pagination
        concerns and would blow the cache if materialised in full. Individual
        rows from the result are folded into the cache as a side-effect.
        """
        stmt = select(Symbol)
        if category is not None:
            stmt = stmt.where(Symbol.category == category)
        stmt = stmt.order_by(Symbol.name.asc())
        async with db_context() as db:
            rows = list((await db.execute(stmt)).scalars().all())
            for r in rows:
                db.expunge(r)
        for r in rows:
            self._cache.setdefault(r.name, r)
        return rows

    async def update_from_terminal(self, terminal_id: str, symbols: list[dict[str, Any]]) -> int:
        """Sync a terminal's advertised symbol list into the ``symbols`` table.

        Resolves the terminal's ``broker_id`` (and ``org_id``) from the
        ``terminals`` table and uses them to scope the upserts — the unique
        constraint on ``symbols`` is ``(broker_id, name)`` so two brokers can
        both expose ``EURUSD`` without colliding.

        Each entry in ``symbols`` is a dict with at least ``name``; optional
        keys mirror ``Symbol`` columns (``digits``, ``category``,
        ``volume_min``, …).

        Returns:
            The number of symbols newly created (updates are not counted).
        """
        if not symbols:
            return 0

        async with db_context() as db:
            # Resolve the terminal → broker_id + org_id.
            t_stmt = select(Terminal).where(Terminal.terminal_id == terminal_id)
            terminal = (await db.execute(t_stmt)).scalar_one_or_none()
            if terminal is None:
                raise ValueError(f"unknown terminal: {terminal_id}")
            broker_id = terminal.broker_id
            org_id = terminal.org_id

            created = 0
            for entry in symbols:
                name = entry.get("name")
                if not name:
                    continue
                stmt = select(Symbol).where(Symbol.name == name, Symbol.broker_id == broker_id)
                existing = (await db.execute(stmt)).scalar_one_or_none()
                fields = {
                    "broker_id": broker_id,
                    "org_id": entry.get("org_id", org_id),
                    "category": entry.get("category"),
                    "digits": entry.get("digits", 5),
                    "description": entry.get("description"),
                    "contract_size": entry.get("contract_size", 1),
                    "volume_min": entry.get("volume_min", 0.01),
                    "volume_step": entry.get("volume_step", 0.01),
                    "volume_max": entry.get("volume_max", 100),
                }
                if existing is None:
                    row = Symbol(name=name, **fields)
                    db.add(row)
                    created += 1
                else:
                    for k, v in fields.items():
                        if v is not None:
                            setattr(existing, k, v)
            await db.commit()

            # Refresh cache: blow away stale entries for these names so the
            # next ``get()`` re-reads from DB. Cheap and correct.
            for entry in symbols:
                name = entry.get("name")
                if name:
                    self._cache.pop(name, None)

        _log.info(
            "symbols_synced_from_terminal",
            terminal_id=terminal_id,
            total=len(symbols),
            created=created,
        )
        return created

    async def get_categories(self) -> list[str]:
        """Return the distinct, non-null categories present in the table."""
        async with db_context() as db:
            stmt = (
                select(Symbol.category)
                .where(Symbol.category.is_not(None))
                .distinct()
                .order_by(Symbol.category.asc())
            )
            rows = (await db.execute(stmt)).scalars().all()
        return [r for r in rows if r]

    # ── Cache management ────────────────────────────────────────────────────

    def invalidate(self, name: str | None = None) -> None:
        """Drop one cached symbol (by name) or the entire cache."""
        if name is None:
            self._cache.clear()
        else:
            self._cache.pop(name, None)

    def cache_size(self) -> int:
        """Number of symbols currently held in the cache."""
        return len(self._cache)


# ── Singleton ────────────────────────────────────────────────────────────────
_service: SymbolService | None = None


def get_symbol_service() -> SymbolService:
    """Return the process-wide ``SymbolService`` singleton."""
    global _service
    if _service is None:
        _service = SymbolService()
    return _service
