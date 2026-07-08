"""List terminals for an org, merged with live status from the bridge registry.

Vertical slice:

  API → query → DB: list Terminals by org_id (optional status filter)
        → bridge registry: list_online() for live status reconciliation
        → return DTOs with both stored and live status

We do NOT mutate the DB rows here — the heartbeat watcher in
:class:`TerminalRegistry` owns the canonical "online/offline/degraded" status.
For the read side we layer live registry status on top of the persisted row
so the UI can show "last seen 5s ago" vs. "online".
"""
from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select

from platform.core.logging import get_logger
from platform.db.models import Terminal
from platform.db.session import db_context
from platform.infrastructure.mt5_bridge.registry import get_registry

_log = get_logger(__name__)


# ── Query + DTO ────────────────────────────────────────────────────────────


class ListTerminalsQuery(BaseModel):
    org_id: UUID
    status: str | None = None  # online | offline | degraded — applied to LIVE status


class TerminalSummary(BaseModel):
    id: UUID
    terminal_id: str  # external
    broker_account: str
    adapter_kind: str
    status: str  # live status (online | offline | degraded)
    last_heartbeat_at: str | None
    version: str | None
    symbols_count: int


class ListTerminalsResult(BaseModel):
    terminals: list[TerminalSummary]
    total: int


# ── Handler ─────────────────────────────────────────────────────────────────


async def handle_list_terminals(query: ListTerminalsQuery) -> ListTerminalsResult:
    """List terminals for the org, overlaying the live registry status."""
    # Snapshot of live terminals — keyed by external terminal_id.
    registry = get_registry()
    live_records = {r.terminal_id: r for r in await registry.list_online()}

    async with db_context() as db:
        stmt = select(Terminal).where(Terminal.org_id == query.org_id)
        stmt = stmt.order_by(Terminal.last_heartbeat_at.desc().nullslast())
        rows = (await db.execute(stmt)).scalars().all()

    summaries: list[TerminalSummary] = []
    for t in rows:
        live = live_records.get(t.terminal_id)
        live_status = live.status if live is not None else "offline"
        # If the DB row says "online" but the registry disagrees, trust the
        # registry — it is the source of truth for liveness.
        if t.status == "online" and live is None:
            live_status = "offline"
        if query.status is not None and live_status != query.status:
            continue

        summaries.append(
            TerminalSummary(
                id=t.id,
                terminal_id=t.terminal_id,
                broker_account=t.broker_account,
                adapter_kind=t.adapter_kind,
                status=live_status,
                last_heartbeat_at=(
                    live.last_heartbeat_at.isoformat()
                    if live
                    else (t.last_heartbeat_at.isoformat() if t.last_heartbeat_at else None)
                ),
                version=t.version,
                symbols_count=len(t.symbols or []),
            )
        )

    return ListTerminalsResult(terminals=summaries, total=len(summaries))
