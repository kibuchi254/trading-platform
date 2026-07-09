"""Pytest configuration — make `platform` importable + provide common fixtures."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Make `platform` importable without shadowing standard library platform module
import platform
ROOT = Path(__file__).resolve().parent.parent
platform_path = ROOT / "src" / "platform"
if not hasattr(platform, "__path__"):
    platform.__path__ = [str(platform_path)]

# Set test environment
os.environ.setdefault("ENV", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://atlas:atlas@localhost:5432/atlas_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-16-chars-long")
os.environ.setdefault("BRIDGE_AUTH_TOKEN", "test-bridge-token")

import pytest


@pytest.fixture
def local_only_bus(monkeypatch):
    """Force the EventBus to operate in local-only mode (no Redis)."""
    import platform.events.bus as bus_mod

    original = bus_mod.EventBus

    class LocalEventBus(original):
        def __init__(self):
            super().__init__()
            self._local_only = True

    monkeypatch.setattr(bus_mod, "EventBus", LocalEventBus)
    # Reset cached singleton
    bus_mod._bus = None
    yield LocalEventBus
    bus_mod._bus = None


@pytest.fixture
def clean_registry():
    """Clear the TerminalRegistry singleton between tests."""
    import platform.infrastructure.mt5_bridge.registry as reg_mod

    reg_mod._registry = None
    yield
    reg_mod._registry = None


@pytest.fixture
def clean_risk_engine():
    """Reset the RiskEngine singleton between tests."""
    import platform.risk.engine as risk_mod

    risk_mod._engine = None
    yield
    risk_mod._engine = None
