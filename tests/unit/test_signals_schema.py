"""Schema regression test for the `signals.status` column + indexes.

Background: the ORM `Signal` model declared a `status` column and a composite
index `ix_signals_org_status_created`, but the initial migration (`0001_initial`)
never created them. As a result `SELECT ... FROM signals` (e.g. the
`/api/v1/signals` endpoint) failed with `column "status" of relation "signals"
does not exist` → HTTP 500. Migration `0002_signal_status` adds the column and
both indexes.

CI runs `alembic upgrade head` against the Postgres service container before
the unit-test suite, so this test runs against the *migration-applied* schema
(not `Base.metadata.create_all`) — i.e. it genuinely exercises migration 0002
and guards against this drift regressing.
"""

from __future__ import annotations

from platform.db.session import db_context

from sqlalchemy import text


async def test_signals_status_column_exists_with_pending_default() -> None:
    """`signals.status` must exist, be non-nullable, and default to 'pending'."""
    async with db_context() as db:
        row = (
            await db.execute(
                text(
                    "SELECT column_default, is_nullable "
                    "FROM information_schema.columns "
                    "WHERE table_name = 'signals' AND column_name = 'status'"
                )
            )
        ).one_or_none()

    assert row is not None, (
        "signals.status column is missing — migration 0002_signal_status not applied"
    )
    assert row.is_nullable == "NO", "signals.status must be NOT NULL"
    assert row.column_default is not None and "pending" in str(row.column_default), (
        f"signals.status default should be 'pending', got {row.column_default!r}"
    )


async def test_signals_status_indexes_exist() -> None:
    """Both the single-column and composite status indexes must exist."""
    expected = {"ix_signals_status", "ix_signals_org_status_created"}
    async with db_context() as db:
        rows = (
            await db.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename = 'signals'")
            )
        ).scalars().all()

    present = set(rows)
    missing = expected - present
    assert not missing, f"signals indexes missing after migration: {sorted(missing)}"
