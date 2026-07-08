"""All ORM models. Grouped by bounded context.

Each context maps to a DDD aggregate cluster — see docs/ATLAS-Architecture.pdf.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from platform.db.base import Base, OrgScopedMixin, SoftDeleteMixin, TimestampMixin, UUIDPKMixin

# ── Identity & Tenancy ─────────────────────────────────────────────────────


class Organization(Base, UUIDPKMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    plan: Mapped[str] = mapped_column(String(40), default="free")  # free | pro | enterprise
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    users: Mapped[list["User"]] = relationship(back_populates="organization")


class User(Base, UUIDPKMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "users"

    org_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(40), default="trader")  # admin | trader | viewer | bot
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped[Organization] = relationship(back_populates="users")


class APIKey(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "api_keys"

    org_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("organizations.id"), index=True)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)  # first 8 chars, for UI display
    key_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    scopes: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ── Brokers & MT5 Terminals ────────────────────────────────────────────────


class Broker(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "brokers"

    org_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)  # exness | icmarkets | pepperstone
    adapter_kind: Mapped[str] = mapped_column(String(40), default="mt5")  # mt5 | fix | crypto | paper
    credentials: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")  # ENCRYPTED at rest
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Terminal(Base, UUIDPKMixin, TimestampMixin):
    """A registered MT5 (or other adapter) terminal.

    The terminal_id is the externally-known identifier (e.g. "mt5-exness-01").
    """
    __tablename__ = "terminals"

    org_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("organizations.id"), index=True)
    broker_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("brokers.id"), index=True)
    terminal_id: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    broker_account: Mapped[str] = mapped_column(String(80), nullable=False)
    adapter_kind: Mapped[str] = mapped_column(String(40), default="mt5")
    version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="offline")  # online | offline | degraded
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    capabilities: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    symbols: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    last_seen_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_terminals_org_status", "org_id", "status"),
    )


# ── Trading ────────────────────────────────────────────────────────────────


class Account(Base, UUIDPKMixin, TimestampMixin):
    """Trading account — a balance against which positions are booked."""
    __tablename__ = "accounts"

    org_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("organizations.id"), index=True)
    terminal_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("terminals.id"), index=True)
    broker_login: Mapped[str] = mapped_column(String(80), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    leverage: Mapped[int] = mapped_column(Integer, default=100)
    equity: Mapped[float] = mapped_column(Numeric(20, 2), default=0)
    balance: Mapped[float] = mapped_column(Numeric(20, 2), default=0)
    margin: Mapped[float] = mapped_column(Numeric(20, 2), default=0)
    free_margin: Mapped[float] = mapped_column(Numeric(20, 2), default=0)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Strategy(Base, UUIDPKMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "strategies"

    org_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(80), nullable=False)  # ema_cross | rsi_reversion | smc_ob | custom
    version: Mapped[str] = mapped_column(String(40), default="1.0.0")
    config: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("org_id", "slug", name="uq_strategies_org_slug"),)


class Signal(Base, UUIDPKMixin, TimestampMixin):
    """A trading signal emitted by a strategy or AI module."""
    __tablename__ = "signals"

    org_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("organizations.id"), index=True)
    strategy_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("strategies.id"), index=True)
    terminal_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("terminals.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)  # buy | sell
    strength: Mapped[float] = mapped_column(Numeric(5, 4), default=0)  # 0.0 - 1.0
    timeframe: Mapped[str] = mapped_column(String(8), default="M1")
    price: Mapped[float] = mapped_column(Numeric(20, 5), nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    source: Mapped[str] = mapped_column(String(40), default="strategy")  # strategy | ai | manual
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # pending | evaluated | executed | expired | rejected

    __table_args__ = (
        Index("ix_signals_org_status_created", "org_id", "status", "created_at"),
    )


class Order(Base, UUIDPKMixin, TimestampMixin):
    """Order — a request to trade. Lives until filled / cancelled / rejected."""
    __tablename__ = "orders"

    org_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("organizations.id"), index=True)
    terminal_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("terminals.id"), index=True)
    strategy_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("strategies.id"), nullable=True)
    signal_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("signals.id"), nullable=True)
    client_order_id: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    broker_order_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)  # buy | sell
    order_type: Mapped[str] = mapped_column(String(20), nullable=False)  # market | limit | stop | stop_limit
    volume: Mapped[float] = mapped_column(Numeric(20, 4), nullable=False)
    price: Mapped[float | None] = mapped_column(Numeric(20, 5), nullable=True)
    stop_loss: Mapped[float | None] = mapped_column(Numeric(20, 5), nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Numeric(20, 5), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # pending | submitted | partial | filled | cancelled | rejected
    filled_volume: Mapped[float] = mapped_column(Numeric(20, 4), default=0)
    avg_fill_price: Mapped[float | None] = mapped_column(Numeric(20, 5), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Execution(Base, UUIDPKMixin, TimestampMixin):
    """An individual fill (an order may have many)."""
    __tablename__ = "executions"

    org_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("organizations.id"), index=True)
    order_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("orders.id"), index=True)
    broker_execution_id: Mapped[str] = mapped_column(String(120), nullable=True)
    volume: Mapped[float] = mapped_column(Numeric(20, 4), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(20, 5), nullable=False)
    commission: Mapped[float] = mapped_column(Numeric(20, 5), default=0)
    swap: Mapped[float] = mapped_column(Numeric(20, 5), default=0)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Position(Base, UUIDPKMixin, TimestampMixin):
    """Open position on a terminal account."""
    __tablename__ = "positions"

    org_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("organizations.id"), index=True)
    terminal_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("terminals.id"), index=True)
    broker_position_id: Mapped[str] = mapped_column(String(80), nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)  # buy | sell
    volume: Mapped[float] = mapped_column(Numeric(20, 4), nullable=False)
    open_price: Mapped[float] = mapped_column(Numeric(20, 5), nullable=False)
    current_price: Mapped[float] = mapped_column(Numeric(20, 5), nullable=False)
    stop_loss: Mapped[float | None] = mapped_column(Numeric(20, 5), nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Numeric(20, 5), nullable=True)
    swap: Mapped[float] = mapped_column(Numeric(20, 5), default=0)
    unrealized_pnl: Mapped[float] = mapped_column(Numeric(20, 2), default=0)
    realized_pnl: Mapped[float] = mapped_column(Numeric(20, 2), default=0)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)  # open | closed

    __table_args__ = (
        Index("ix_positions_org_terminal_status", "org_id", "terminal_id", "status"),
    )


class Trade(Base, UUIDPKMixin, TimestampMixin):
    """Closed trade — historical record."""
    __tablename__ = "trades"

    org_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("organizations.id"), index=True)
    position_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("positions.id"), index=True)
    strategy_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("strategies.id"), nullable=True)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    volume: Mapped[float] = mapped_column(Numeric(20, 4), nullable=False)
    entry_price: Mapped[float] = mapped_column(Numeric(20, 5), nullable=False)
    exit_price: Mapped[float] = mapped_column(Numeric(20, 5), nullable=False)
    pnl: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False)
    pips: Mapped[float] = mapped_column(Numeric(20, 2), default=0)
    commission: Mapped[float] = mapped_column(Numeric(20, 5), default=0)
    swap: Mapped[float] = mapped_column(Numeric(20, 5), default=0)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ── Market Data ────────────────────────────────────────────────────────────


class Symbol(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "symbols"

    org_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)  # null = shared
    broker_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("brokers.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category: Mapped[str | None] = mapped_column(String(40), nullable=True)  # fx | metals | crypto | indices
    digits: Mapped[int] = mapped_column(Integer, default=5)
    contract_size: Mapped[float] = mapped_column(Numeric(20, 4), default=1)
    volume_min: Mapped[float] = mapped_column(Numeric(20, 4), default=0.01)
    volume_step: Mapped[float] = mapped_column(Numeric(20, 4), default=0.01)
    volume_max: Mapped[float] = mapped_column(Numeric(20, 4), default=100)

    __table_args__ = (UniqueConstraint("broker_id", "name", name="uq_symbols_broker_name"),)


class Tick(Base):
    """Raw tick storage. Partitioned by month in production.

    For high throughput, swap the underlying table for a TimescaleDB hypertable
    (see docs → Scaling Strategy)."""
    __tablename__ = "ticks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    terminal_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("terminals.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    bid: Mapped[float] = mapped_column(Numeric(20, 5), nullable=False)
    ask: Mapped[float] = mapped_column(Numeric(20, 5), nullable=False)
    last: Mapped[float | None] = mapped_column(Numeric(20, 5), nullable=True)
    volume: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    __table_args__ = (
        Index("ix_ticks_symbol_ts", "symbol", "ts"),
    )


class Candle(Base):
    """OHLC cache for arbitrary timeframes."""
    __tablename__ = "candles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    terminal_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("terminals.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)  # M1 | M5 | M15 | H1 | H4 | D1
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[float] = mapped_column(Numeric(20, 5), nullable=False)
    high: Mapped[float] = mapped_column(Numeric(20, 5), nullable=False)
    low: Mapped[float] = mapped_column(Numeric(20, 5), nullable=False)
    close: Mapped[float] = mapped_column(Numeric(20, 5), nullable=False)
    volume: Mapped[float] = mapped_column(Numeric(20, 4), default=0)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        UniqueConstraint("terminal_id", "symbol", "timeframe", "ts", name="uq_candles_term_sym_tf_ts"),
    )


# ── AI / Risk / Audit ───────────────────────────────────────────────────────


class AIResult(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "ai_results"

    org_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("organizations.id"), index=True)
    module: Mapped[str] = mapped_column(String(40), nullable=False, index=True)  # trend | pattern | risk | ...
    symbol: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    timeframe: Mapped[str | None] = mapped_column(String(8), nullable=True)
    prediction: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), default=0)
    model_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class RiskEvent(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "risk_events"

    org_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("organizations.id"), index=True)
    terminal_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("terminals.id"), nullable=True)
    rule: Mapped[str] = mapped_column(String(60), nullable=False, index=True)  # drawdown | exposure | news_lock | kill_switch
    severity: Mapped[str] = mapped_column(String(20), default="warning")  # info | warning | critical | kill
    action: Mapped[str] = mapped_column(String(40), default="log")  # log | block | close_all | disable
    details: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    order_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("orders.id"), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), index=True)
    actor_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), index=True)
    actor_type: Mapped[str] = mapped_column(String(20), default="user")  # user | api_key | system
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Notification(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "notifications"

    org_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("organizations.id"), index=True)
    user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)  # email | telegram | discord | webhook | in_app
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | sent | failed
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)


class Backtest(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "backtests"

    org_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("organizations.id"), index=True)
    strategy_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("strategies.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    initial_capital: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False)
    final_equity: Mapped[float | None] = mapped_column(Numeric(20, 2), nullable=True)
    max_drawdown: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    sharpe: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    trades_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    config: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    results: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
