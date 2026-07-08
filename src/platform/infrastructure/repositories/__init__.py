"""Repository package — one file per aggregate, all re-exported here.

Usage:

    from platform.infrastructure.repositories import get_repositories, Repositories

    async with db_context() as session:
        repos = get_repositories(session)
        order = await repos.orders.get(order_id)
        await repos.terminals.update_heartbeat(terminal_id, status="online")

The `Repositories` dataclass holds a single instance of every repository,
all sharing the same `AsyncSession` — so a single unit-of-work commit flushes
every aggregate written through it.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from platform.infrastructure.repositories.account_repository import AccountRepository
from platform.infrastructure.repositories.ai_result_repository import AIResultRepository
from platform.infrastructure.repositories.api_key_repository import APIKeyRepository
from platform.infrastructure.repositories.audit_repository import AuditRepository
from platform.infrastructure.repositories.backtest_repository import BacktestRepository
from platform.infrastructure.repositories.market_data_repository import MarketDataRepository
from platform.infrastructure.repositories.order_repository import OrderRepository
from platform.infrastructure.repositories.position_repository import PositionRepository
from platform.infrastructure.repositories.risk_event_repository import RiskEventRepository
from platform.infrastructure.repositories.signal_repository import SignalRepository
from platform.infrastructure.repositories.strategy_repository import StrategyRepository
from platform.infrastructure.repositories.terminal_repository import TerminalRepository
from platform.infrastructure.repositories.trade_repository import TradeRepository
from platform.infrastructure.repositories.user_repository import UserRepository


@dataclass(slots=True)
class Repositories:
    """A bundle of every repository, all bound to one AsyncSession."""
    session: AsyncSession
    accounts: AccountRepository
    ai_results: AIResultRepository
    api_keys: APIKeyRepository
    audit: AuditRepository
    backtests: BacktestRepository
    market_data: MarketDataRepository
    orders: OrderRepository
    positions: PositionRepository
    risk_events: RiskEventRepository
    signals: SignalRepository
    strategies: StrategyRepository
    terminals: TerminalRepository
    trades: TradeRepository
    users: UserRepository


def get_repositories(session: AsyncSession) -> Repositories:
    """Construct a `Repositories` bundle bound to the given session.

    All repositories share the same session — commit/rollback on the session
    flushes every aggregate written through the bundle.
    """
    return Repositories(
        session=session,
        accounts=AccountRepository(session),
        ai_results=AIResultRepository(session),
        api_keys=APIKeyRepository(session),
        audit=AuditRepository(session),
        backtests=BacktestRepository(session),
        market_data=MarketDataRepository(session),
        orders=OrderRepository(session),
        positions=PositionRepository(session),
        risk_events=RiskEventRepository(session),
        signals=SignalRepository(session),
        strategies=StrategyRepository(session),
        terminals=TerminalRepository(session),
        trades=TradeRepository(session),
        users=UserRepository(session),
    )


__all__ = [
    "Repositories", "get_repositories",
    "AccountRepository", "AIResultRepository", "APIKeyRepository",
    "AuditRepository", "BacktestRepository", "MarketDataRepository",
    "OrderRepository", "PositionRepository", "RiskEventRepository",
    "SignalRepository", "StrategyRepository", "TerminalRepository",
    "TradeRepository", "UserRepository",
]
