"""Application commands — CQRS write side.

Each command is a use case: validate input, run domain logic, persist, emit events.
Commands are pure functions over (db, services, command) -> result.

Every command + result pair is a Pydantic model. Handlers are
``async def handle_<command>(cmd) -> Result`` and use ``db_context()``
for DB access, ``get_bridge_client()`` / ``get_adapter_registry()`` for
execution, and ``get_risk_engine()`` for risk checks. Events are published
to the event bus where appropriate.
"""
from __future__ import annotations

from platform.application.commands.place_order import (
    PlaceOrderCommand,
    PlaceOrderResult,
    handle_place_order,
)
from platform.application.commands.cancel_order import (
    CancelOrderCommand,
    CancelOrderResult,
    handle_cancel_order,
)
from platform.application.commands.close_position import (
    ClosePositionCommand,
    ClosePositionResult,
    handle_close_position,
)
from platform.application.commands.modify_position import (
    ModifyPositionCommand,
    ModifyPositionResult,
    handle_modify_position,
)
from platform.application.commands.sync_terminal import (
    SyncTerminalCommand,
    SyncTerminalResult,
    handle_sync_terminal,
)
from platform.application.commands.subscribe_ticks import (
    SubscribeTicksCommand,
    SubscribeTicksResult,
    handle_subscribe_ticks,
)
from platform.application.commands.register_strategy import (
    RegisterStrategyCommand,
    RegisterStrategyResult,
    handle_register_strategy,
)
from platform.application.commands.create_strategy import (
    CreateStrategyCommand,
    handle_create_strategy,
)
from platform.application.commands.activate_strategy import (
    ActivateStrategyCommand,
    ActivateStrategyResult,
    handle_activate_strategy,
)
from platform.application.commands.run_backtest import (
    RunBacktestCommand,
    RunBacktestResult,
    handle_run_backtest,
)
from platform.application.commands.engage_kill_switch import (
    EngageKillSwitchCommand,
    EngageKillSwitchResult,
    handle_engage_kill_switch,
)
from platform.application.commands.flatten_all import (
    FlattenAllCommand,
    FlattenAllResult,
    handle_flatten_all,
)
from platform.application.commands.sync_positions import (
    SyncPositionsCommand,
    handle_sync_positions,
)
from platform.application.commands.sync_account import (
    SyncAccountCommand,
    handle_sync_account,
)
from platform.application.commands.register_terminal import (
    RegisterTerminalCommand,
    handle_register_terminal,
)
from platform.application.commands.create_user import (
    CreateUserCommand,
    CreateUserResult,
    handle_create_user,
)

__all__ = [
    # Place / cancel / close / modify
    "PlaceOrderCommand", "PlaceOrderResult", "handle_place_order",
    "CancelOrderCommand", "CancelOrderResult", "handle_cancel_order",
    "ClosePositionCommand", "ClosePositionResult", "handle_close_position",
    "ModifyPositionCommand", "ModifyPositionResult", "handle_modify_position",
    # Terminal lifecycle
    "RegisterTerminalCommand", "handle_register_terminal",
    "SyncTerminalCommand", "SyncTerminalResult", "handle_sync_terminal",
    "SyncPositionsCommand", "handle_sync_positions",
    "SyncAccountCommand", "handle_sync_account",
    "SubscribeTicksCommand", "SubscribeTicksResult", "handle_subscribe_ticks",
    # Strategies + backtests
    "CreateStrategyCommand", "handle_create_strategy",
    "RegisterStrategyCommand", "RegisterStrategyResult", "handle_register_strategy",
    "ActivateStrategyCommand", "ActivateStrategyResult", "handle_activate_strategy",
    "RunBacktestCommand", "RunBacktestResult", "handle_run_backtest",
    # Risk / kill switch / emergency
    "EngageKillSwitchCommand", "EngageKillSwitchResult", "handle_engage_kill_switch",
    "FlattenAllCommand", "FlattenAllResult", "handle_flatten_all",
    # Identity
    "CreateUserCommand", "CreateUserResult", "handle_create_user",
]
