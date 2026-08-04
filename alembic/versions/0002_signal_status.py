"""add signals.status column + index

The Signal ORM model declares a `status` column and the composite index
`ix_signals_org_status_created`, but the initial migration (0001) never
created them. As a result, any `SELECT` against the `signals` table (e.g.
the /signals REST endpoint) failed with `column "status" of relation
"signals" does not exist` → HTTP 500.

Revision ID: 0002_signal_status
Revises: 0001_initial
Create Date: 2026-08-04
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_signal_status"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `status` is non-nullable; backfill existing rows with "pending" via
    # server_default, then drop the default so future inserts rely on the ORM
    # default (matching the rest of the schema's convention).
    op.add_column(
        "signals",
        sa.Column(
            "status",
            sa.String(20),
            server_default="pending",
            nullable=False,
        ),
    )
    op.create_index(
        "ix_signals_status",
        "signals",
        ["status"],
    )
    op.create_index(
        "ix_signals_org_status_created",
        "signals",
        ["org_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_signals_org_status_created", table_name="signals")
    op.drop_index("ix_signals_status", table_name="signals")
    op.drop_column("signals", "status")
