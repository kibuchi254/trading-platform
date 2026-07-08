"""Test the StrategySandbox — security validation of user-uploaded strategies."""
from __future__ import annotations

import pytest

from platform.plugins.sandbox import StrategySandbox


@pytest.fixture
def sandbox():
    return StrategySandbox()


async def test_valid_strategy_passes(sandbox) -> None:
    code = '''
from platform.strategies.sdk import Strategy, Bar, Signal, StrategyContext, strategy

@strategy
class MyStrategy(Strategy):
    name = "my_test_strategy"
    version = "1.0.0"
    default_config = {"period": 14}

    def __init__(self, *, period: int = 14):
        self.period = period

    async def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal | None:
        return None
'''
    is_valid, error = await sandbox.validate(code)
    assert is_valid, f"Expected valid, got: {error}"


async def test_rejects_subprocess_import(sandbox) -> None:
    code = "import subprocess\nsubprocess.run(['rm', '-rf', '/'])"
    is_valid, error = await sandbox.validate(code)
    assert not is_valid
    assert "subprocess" in error or "forbidden" in error.lower()


async def test_rejects_os_import(sandbox) -> None:
    code = "import os\nos.system('whoami')"
    is_valid, error = await sandbox.validate(code)
    assert not is_valid


async def test_rejects_eval(sandbox) -> None:
    code = "x = eval('__import__(\"os\").system(\"id\")')"
    is_valid, error = await sandbox.validate(code)
    assert not is_valid


async def test_rejects_exec(sandbox) -> None:
    code = "exec('import os')"
    is_valid, error = await sandbox.validate(code)
    assert not is_valid


async def test_rejects_open_call(sandbox) -> None:
    code = "f = open('/etc/passwd')"
    is_valid, error = await sandbox.validate(code)
    assert not is_valid


async def test_rejects_socket_import(sandbox) -> None:
    code = "import socket\ns = socket.socket()"
    is_valid, error = await sandbox.validate(code)
    assert not is_valid


async def test_rejects_syntax_error(sandbox) -> None:
    code = "def broken(:"
    is_valid, error = await sandbox.validate(code)
    assert not is_valid
    assert "syntax" in error.lower() or "compile" in error.lower()


async def test_allows_numpy_import(sandbox) -> None:
    code = "import numpy as np\narr = np.array([1,2,3])"
    is_valid, error = await sandbox.validate(code)
    assert is_valid


async def test_allows_pandas_import(sandbox) -> None:
    code = "import pandas as pd\ndf = pd.DataFrame()"
    is_valid, error = await sandbox.validate(code)
    assert is_valid


async def test_allows_math_import(sandbox) -> None:
    code = "import math\nx = math.sqrt(16)"
    is_valid, error = await sandbox.validate(code)
    assert is_valid


async def test_rejects_dunder_import(sandbox) -> None:
    code = "os = __import__('os')"
    is_valid, error = await sandbox.validate(code)
    assert not is_valid
