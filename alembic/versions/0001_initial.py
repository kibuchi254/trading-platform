"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-09
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Organizations + Users ──────────────────────────────────────────────
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(80), unique=True, nullable=False),
        sa.Column("plan", sa.String(40), server_default="free"),
        sa.Column("settings", postgresql.JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), index=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("role", sa.String(40), server_default="trader"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), index=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), index=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("key_prefix", sa.String(12), nullable=False),
        sa.Column("key_hash", sa.String(255), unique=True, nullable=False),
        sa.Column("scopes", postgresql.JSONB, server_default="[]"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── Brokers + Terminals ────────────────────────────────────────────────
    op.create_table(
        "brokers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), index=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("adapter_kind", sa.String(40), server_default="mt5"),
        sa.Column("credentials", postgresql.JSONB, server_default="{}"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "terminals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), index=True),
        sa.Column("broker_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("brokers.id"), index=True),
        sa.Column("terminal_id", sa.String(80), unique=True, nullable=False, index=True),
        sa.Column("broker_account", sa.String(80), nullable=False),
        sa.Column("adapter_kind", sa.String(40), server_default="mt5"),
        sa.Column("version", sa.String(40), nullable=True),
        sa.Column("status", sa.String(20), server_default="offline"),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("capabilities", postgresql.JSONB, server_default="{}"),
        sa.Column("symbols", postgresql.JSONB, server_default="[]"),
        sa.Column("settings", postgresql.JSONB, server_default="{}"),
        sa.Column("last_seen_ip", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_terminals_org_status", "terminals", ["org_id", "status"])

    # ── Trading ────────────────────────────────────────────────────────────
    op.create_table(
        "accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), index=True),
        sa.Column("terminal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("terminals.id"), index=True),
        sa.Column("broker_login", sa.String(80), nullable=False),
        sa.Column("currency", sa.String(8), server_default="USD"),
        sa.Column("leverage", sa.Integer, server_default="100"),
        sa.Column("equity", sa.Numeric(20, 2), server_default="0"),
        sa.Column("balance", sa.Numeric(20, 2), server_default="0"),
        sa.Column("margin", sa.Numeric(20, 2), server_default="0"),
        sa.Column("free_margin", sa.Numeric(20, 2), server_default="0"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "strategies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), index=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(80), nullable=False),
        sa.Column("version", sa.String(40), server_default="1.0.0"),
        sa.Column("config", postgresql.JSONB, server_default="{}"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("org_id", "slug", name="uq_strategies_org_slug"),
    )

    op.create_table(
        "signals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), index=True),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("strategies.id"), index=True),
        sa.Column("terminal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("terminals.id"), index=True),
        sa.Column("symbol", sa.String(40), nullable=False, index=True),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("strength", sa.Numeric(5, 4), server_default="0"),
        sa.Column("timeframe", sa.String(8), server_default="M1"),
        sa.Column("price", sa.Numeric(20, 5), nullable=False),
        sa.Column("meta", postgresql.JSONB, server_default="{}"),
        sa.Column("source", sa.String(40), server_default="strategy"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), index=True),
        sa.Column("terminal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("terminals.id"), index=True),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("strategies.id"), nullable=True),
        sa.Column("signal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("signals.id"), nullable=True),
        sa.Column("client_order_id", sa.String(80), unique=True, nullable=False, index=True),
        sa.Column("broker_order_id", sa.String(80), nullable=True, index=True),
        sa.Column("symbol", sa.String(40), nullable=False, index=True),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("order_type", sa.String(20), nullable=False),
        sa.Column("volume", sa.Numeric(20, 4), nullable=False),
        sa.Column("price", sa.Numeric(20, 5), nullable=True),
        sa.Column("stop_loss", sa.Numeric(20, 5), nullable=True),
        sa.Column("take_profit", sa.Numeric(20, 5), nullable=True),
        sa.Column("status", sa.String(20), server_default="pending", index=True),
        sa.Column("filled_volume", sa.Numeric(20, 4), server_default="0"),
        sa.Column("avg_fill_price", sa.Numeric(20, 5), nullable=True),
        sa.Column("rejection_reason", sa.String(255), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), index=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id"), index=True),
        sa.Column("broker_execution_id", sa.String(120), nullable=True),
        sa.Column("volume", sa.Numeric(20, 4), nullable=False),
        sa.Column("price", sa.Numeric(20, 5), nullable=False),
        sa.Column("commission", sa.Numeric(20, 5), server_default="0"),
        sa.Column("swap", sa.Numeric(20, 5), server_default="0"),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "positions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), index=True),
        sa.Column("terminal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("terminals.id"), index=True),
        sa.Column("broker_position_id", sa.String(80), nullable=True, index=True),
        sa.Column("symbol", sa.String(40), nullable=False, index=True),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("volume", sa.Numeric(20, 4), nullable=False),
        sa.Column("open_price", sa.Numeric(20, 5), nullable=False),
        sa.Column("current_price", sa.Numeric(20, 5), nullable=False),
        sa.Column("stop_loss", sa.Numeric(20, 5), nullable=True),
        sa.Column("take_profit", sa.Numeric(20, 5), nullable=True),
        sa.Column("swap", sa.Numeric(20, 5), server_default="0"),
        sa.Column("unrealized_pnl", sa.Numeric(20, 2), server_default="0"),
        sa.Column("realized_pnl", sa.Numeric(20, 2), server_default="0"),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), server_default="open", index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_positions_org_terminal_status", "positions", ["org_id", "terminal_id", "status"])

    op.create_table(
        "trades",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), index=True),
        sa.Column("position_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("positions.id"), index=True),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("strategies.id"), nullable=True),
        sa.Column("symbol", sa.String(40), nullable=False, index=True),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("volume", sa.Numeric(20, 4), nullable=False),
        sa.Column("entry_price", sa.Numeric(20, 5), nullable=False),
        sa.Column("exit_price", sa.Numeric(20, 5), nullable=False),
        sa.Column("pnl", sa.Numeric(20, 2), nullable=False),
        sa.Column("pips", sa.Numeric(20, 2), server_default="0"),
        sa.Column("commission", sa.Numeric(20, 5), server_default="0"),
        sa.Column("swap", sa.Numeric(20, 5), server_default="0"),
        sa.Column("duration_seconds", sa.Integer, server_default="0"),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── Market Data ────────────────────────────────────────────────────────
    op.create_table(
        "symbols",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("broker_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("brokers.id"), nullable=True),
        sa.Column("name", sa.String(40), nullable=False, index=True),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("category", sa.String(40), nullable=True),
        sa.Column("digits", sa.Integer, server_default="5"),
        sa.Column("contract_size", sa.Numeric(20, 4), server_default="1"),
        sa.Column("volume_min", sa.Numeric(20, 4), server_default="0.01"),
        sa.Column("volume_step", sa.Numeric(20, 4), server_default="0.01"),
        sa.Column("volume_max", sa.Numeric(20, 4), server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("broker_id", "name", name="uq_symbols_broker_name"),
    )

    op.create_table(
        "ticks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("terminal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("terminals.id"), index=True),
        sa.Column("symbol", sa.String(40), nullable=False, index=True),
        sa.Column("bid", sa.Numeric(20, 5), nullable=False),
        sa.Column("ask", sa.Numeric(20, 5), nullable=False),
        sa.Column("last", sa.Numeric(20, 5), nullable=True),
        sa.Column("volume", sa.Numeric(20, 4), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, index=True),
    )
    op.create_index("ix_ticks_symbol_ts", "ticks", ["symbol", "ts"])

    op.create_table(
        "candles",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("terminal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("terminals.id"), index=True),
        sa.Column("symbol", sa.String(40), nullable=False, index=True),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(20, 5), nullable=False),
        sa.Column("high", sa.Numeric(20, 5), nullable=False),
        sa.Column("low", sa.Numeric(20, 5), nullable=False),
        sa.Column("close", sa.Numeric(20, 5), nullable=False),
        sa.Column("volume", sa.Numeric(20, 4), server_default="0"),
        sa.Column("is_closed", sa.Boolean, server_default="false"),
        sa.UniqueConstraint("terminal_id", "symbol", "timeframe", "ts", name="uq_candles_term_sym_tf_ts"),
    )

    # ── AI / Risk / Audit ──────────────────────────────────────────────────
    op.create_table(
        "ai_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), index=True),
        sa.Column("module", sa.String(40), nullable=False, index=True),
        sa.Column("symbol", sa.String(40), nullable=True, index=True),
        sa.Column("timeframe", sa.String(8), nullable=True),
        sa.Column("prediction", postgresql.JSONB, server_default="{}"),
        sa.Column("confidence", sa.Numeric(5, 4), server_default="0"),
        sa.Column("model_version", sa.String(40), nullable=True),
        sa.Column("input_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "risk_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), index=True),
        sa.Column("terminal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("terminals.id"), nullable=True),
        sa.Column("rule", sa.String(60), nullable=False, index=True),
        sa.Column("severity", sa.String(20), server_default="warning"),
        sa.Column("action", sa.String(40), server_default="log"),
        sa.Column("details", postgresql.JSONB, server_default="{}"),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), index=True, nullable=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), index=True, nullable=True),
        sa.Column("actor_type", sa.String(20), server_default="user"),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("resource_type", sa.String(40), nullable=True),
        sa.Column("resource_id", sa.String(80), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column("payload", postgresql.JSONB, server_default="{}"),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
    )

    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), index=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("subject", sa.String(255), nullable=True),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), server_default="pending"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "backtests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), index=True),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("strategies.id"), index=True),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("initial_capital", sa.Numeric(20, 2), nullable=False),
        sa.Column("final_equity", sa.Numeric(20, 2), nullable=True),
        sa.Column("max_drawdown", sa.Numeric(8, 4), nullable=True),
        sa.Column("sharpe", sa.Numeric(8, 4), nullable=True),
        sa.Column("trades_count", sa.Integer, server_default="0"),
        sa.Column("status", sa.String(20), server_default="pending"),
        sa.Column("config", postgresql.JSONB, server_default="{}"),
        sa.Column("results", postgresql.JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    for t in (
        "backtests", "notifications", "audit_logs", "risk_events", "ai_results",
        "candles", "ticks", "symbols", "trades", "positions", "executions",
        "orders", "signals", "strategies", "accounts", "terminals", "brokers",
        "api_keys", "users", "organizations",
    ):
        op.drop_table(t)
