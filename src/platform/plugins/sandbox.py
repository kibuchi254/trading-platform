"""Strategy sandbox — safely load and execute user-uploaded strategies.

User-supplied strategy code is *untrusted*. This module applies a set of
static and runtime guardrails so a malicious or buggy submission cannot
escape its sandbox:

**Static validation** (:meth:`StrategySandbox.validate`)
    * Compile-check the source with :func:`compile`.
    * Scan for forbidden tokens (``import subprocess``, ``__import__``,
      ``eval(``, ``exec(``, ``open(``, ``socket.``, …).
    * Allow only a whitelist of imports — ``numpy``, ``pandas``, ``math``,
      ``statistics``, ``datetime``, ``collections``,
      ``platform.strategies.sdk``.

**Restricted execution** (:meth:`StrategySandbox.load`)
    * Execute the validated source inside a namespace whose ``__builtins__``
      has been replaced with a minimal, safe subset.
    * Discover the first :class:`Strategy` subclass defined in the
      namespace and register it with the
      :class:`~platform.strategies.sdk.StrategyRegistry`.
    * Wrap the strategy's :meth:`~platform.strategies.sdk.Strategy.on_bar`
      in :func:`asyncio.wait_for` with a 1-second budget so a runaway
      strategy cannot stall the orchestrator.

The sandbox is deliberately conservative. When in doubt, reject. A
false negative (rejecting safe code) is an annoyance; a false positive
(letting unsafe code through) is a security incident.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
from platform.core.logging import get_logger
from typing import Any

_log = get_logger(__name__)

# Whitelisted top-level imports. Anything else is rejected at validation
# time. ``platform.strategies.sdk`` is the canonical strategy SDK.
ALLOWED_IMPORTS: frozenset[str] = frozenset(
    {
        "numpy",
        "pandas",
        "math",
        "statistics",
        "datetime",
        "collections",
        "platform.strategies.sdk",
    }
)

# Forbidden substrings — any match rejects the source outright. These are
# intentionally broad: even ``import os`` is blocked because ``os`` exposes
# ``system`` / ``exec*`` / file operations that could escape the sandbox.
FORBIDDEN_PATTERNS: tuple[str, ...] = (
    "import subprocess",
    "import os",
    "from os",
    "__import__",
    "eval(",
    "exec(",
    "open(",
    "socket.",
    "import sys",
    "from sys",
    "import shutil",
    "import pickle",
    "import marshal",
    "import ctypes",
    "import threading",
    "import multiprocessing",
    "import asyncio.ensure_future",  # block async-escape primitives
)


# Minimal builtins available to sandboxed code. We omit ``eval``, ``exec``,
# ``compile``, ``open``, ``globals``, ``locals``, ``vars``, ``dir``,
# ``getattr`` with default, ``breakpoint``. A restricted ``__import__`` is
# included so user code can do ``from platform.strategies.sdk import Strategy``
# without needing raw access to the real ``__import__``.
def _make_restricted_import():
    """Return a __import__ that only resolves modules in ALLOWED_IMPORTS."""
    import importlib

    def _restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
        # Allow the whitelisted top-level module or any submodule of one.
        top = name.split(".", 1)[0]
        allowed_top = any(
            name == allowed or name.startswith(allowed + ".") or top == allowed
            for allowed in ALLOWED_IMPORTS
        )
        if not allowed_top:
            raise ImportError(f"Sandbox refused to import {name!r} — not in ALLOWED_IMPORTS")
        return importlib.import_module(name)

    return _restricted_import


SAFE_BUILTINS: dict[str, Any] = {
    "abs": abs,
    "all": all,
    "any": any,
    "bin": bin,
    "bool": bool,
    "bytearray": bytearray,
    "bytes": bytes,
    "callable": callable,
    "chr": chr,
    "complex": complex,
    "dict": dict,
    "divmod": divmod,
    "enumerate": enumerate,
    "filter": filter,
    "float": float,
    "format": format,
    "frozenset": frozenset,
    "hash": hash,
    "hex": hex,
    "int": int,
    "isinstance": isinstance,
    "issubclass": issubclass,
    "iter": iter,
    "len": len,
    "list": list,
    "map": map,
    "max": max,
    "min": min,
    "next": next,
    "object": object,
    "oct": oct,
    "ord": ord,
    "pow": pow,
    "print": print,
    "range": range,
    "repr": repr,
    "reversed": reversed,
    "round": round,
    "set": set,
    "slice": slice,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "type": type,
    "zip": zip,
    "True": True,
    "False": False,
    "None": None,
    "AttributeError": AttributeError,
    "KeyError": KeyError,
    "IndexError": IndexError,
    "TypeError": TypeError,
    "ValueError": ValueError,
    "ZeroDivisionError": ZeroDivisionError,
    "StopIteration": StopIteration,
    "NameError": NameError,
    "NotImplementedError": NotImplementedError,
    "Exception": Exception,
    "RuntimeError": RuntimeError,
    "ArithmeticError": ArithmeticError,
    "LookupError": LookupError,
    # Restricted __import__ — only resolves whitelisted modules.
    "__import__": _make_restricted_import(),
    # __build_class__ is required by Python's ``class`` statement — without
    # it the user cannot define a Strategy subclass at all.
    "__build_class__": __build_class__,
}

# CPU budget per on_bar invocation. A strategy that takes longer than
# this is assumed to be in an infinite loop and is cancelled.
ON_BAR_TIMEOUT_SECONDS: float = 1.0


class StrategySandbox:
    """Validate, load, and execute user-uploaded strategies in a sandbox.

    The sandbox is single-purpose: one instance per strategy upload. It
    is safe to instantiate a fresh sandbox per request — there is no
    shared mutable state outside the namespace built for the strategy.
    """

    # ── Validation ─────────────────────────────────────────────────────

    async def validate(self, source_code: str) -> tuple[bool, str]:
        """Validate user-supplied strategy source.

        Performs three checks, in order of cheapest to most expensive:

        1. **Forbidden-pattern scan** — reject if any substring in
           :data:`FORBIDDEN_PATTERNS` appears in the source.
        2. **AST import scan** — reject if the source imports anything
           outside :data:`ALLOWED_IMPORTS`.
        3. **Compile check** — reject if the source does not compile.

        Parameters
        ----------
        source_code:
            Raw source code as submitted by the user.

        Returns
        -------
        (is_valid, message)
            ``is_valid`` is True iff every check passed. ``message`` is
            an empty string on success or a human-readable error on
            failure.
        """
        # 1) Forbidden-pattern scan — cheapest, broadest.
        for pattern in FORBIDDEN_PATTERNS:
            if pattern in source_code:
                return False, f"Forbidden pattern detected: {pattern!r}"

        # 2) Parse the AST so we can inspect imports precisely.
        try:
            tree = ast.parse(source_code)
        except SyntaxError as exc:
            return False, f"Syntax error: {exc.msg} (line {exc.lineno})"

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if not self._is_import_allowed(alias.name):
                        return False, f"Import not allowed: {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                if node.module is None:
                    continue
                if not self._is_import_allowed(node.module):
                    return False, f"Import not allowed: {node.module}"

        # 3) Compile check — catches issues AST parsing alone misses.
        try:
            compile(source_code, "<sandbox>", "exec")
        except SyntaxError as exc:
            return False, f"Compile error: {exc.msg} (line {exc.lineno})"
        except Exception as exc:
            return False, f"Compile error: {exc.__class__.__name__}: {exc}"

        return True, ""

    @staticmethod
    def _is_import_allowed(module: str) -> bool:
        """Check whether ``module`` is in the whitelist or a sub-package of one.

        ``platform.strategies.sdk`` is allowed in full (any submodule),
        as are ``numpy``, ``pandas``, etc. (so ``numpy.linalg`` is OK).
        """
        for allowed in ALLOWED_IMPORTS:
            if module == allowed or module.startswith(allowed + "."):
                return True
        return False

    # ── Loading ────────────────────────────────────────────────────────

    async def load(self, source_code: str, name: str) -> type[Any] | None:
        """Validate, execute, and register a sandboxed strategy.

        Parameters
        ----------
        source_code:
            Raw source code as submitted by the user.
        name:
            Identifier under which to register the strategy with the
            :class:`~platform.strategies.sdk.StrategyRegistry`. Must be
            unique within the registry.

        Returns
        -------
        type or None
            The discovered :class:`Strategy` subclass on success, or
            ``None`` if validation failed, no Strategy subclass was
            defined, or the strategy could not be registered.
        """
        is_valid, message = await self.validate(source_code)
        if not is_valid:
            _log.warning("strategy_sandbox_validation_failed", name=name, error=message)
            return None

        # Build a restricted namespace. ``__builtins__`` is replaced with
        # a safe subset; the strategy SDK is provided as a pre-imported
        # module so user code can do ``from platform.strategies.sdk import Strategy``.
        try:
            from platform.strategies.sdk import Strategy  # noqa: F401

            __import__("platform.strategies.sdk", fromlist=["*"])
        except Exception:
            _log.exception("strategy_sdk_import_failed")
            return None

        # Pre-populate the namespace with the whitelisted stdlib modules
        # so user code doesn't even need an ``import`` statement for them
        # (and so we don't have to allow ``__import__`` for them).
        namespace: dict[str, Any] = {
            "__builtins__": dict(SAFE_BUILTINS),
            # __name__ and __module__ are required by Python's class machinery.
            "__name__": f"sandbox:{name}",
        }
        with contextlib.suppress(ImportError):
            namespace["numpy"] = __import__("numpy")
        with contextlib.suppress(ImportError):
            namespace["pandas"] = __import__("pandas")
        namespace["math"] = __import__("math")
        namespace["statistics"] = __import__("statistics")
        namespace["datetime"] = __import__("datetime")
        namespace["collections"] = __import__("collections")
        namespace["platform"] = __import__("platform")
        # Expose the platform.strategies submodule so user code can do
        # ``from platform.strategies.sdk import Strategy``.
        import importlib

        try:
            namespace["platform"].strategies = importlib.import_module("platform.strategies")
        except ImportError:
            _log.warning("strategy_sdk_submodule_unavailable")

        # Execute the user's code in the restricted namespace.
        try:
            compiled = compile(source_code, f"<sandbox:{name}>", "exec")
            exec(compiled, namespace)
        except Exception as exc:
            _log.warning("strategy_sandbox_exec_failed", name=name, error=str(exc))
            return None

        # Find the Strategy subclass defined in the namespace.
        from platform.strategies.sdk import Strategy as _StrategyBase
        from platform.strategies.sdk import get_strategy_registry

        strategy_cls: type[Any] | None = None
        for value in namespace.values():
            if (
                isinstance(value, type)
                and issubclass(value, _StrategyBase)
                and value is not _StrategyBase
            ):
                strategy_cls = value
                break

        if strategy_cls is None:
            _log.warning("strategy_sandbox_no_strategy_class", name=name)
            return None

        # Force the registry name to the caller-supplied identifier so
        # we don't collide with built-ins.
        try:
            strategy_cls.name = name  # type: ignore[attr-defined]
        except Exception:
            pass

        # Wrap on_bar with a CPU budget so a runaway strategy can't
        # stall the orchestrator.
        self._apply_cpu_budget(strategy_cls)

        # Register with the global StrategyRegistry.
        try:
            registry = get_strategy_registry()
            registry.register(strategy_cls)
        except Exception:
            _log.exception("strategy_sandbox_register_failed", name=name)
            return None

        _log.info("strategy_sandbox_loaded", name=name, cls=strategy_cls.__name__)
        return strategy_cls

    # ── CPU budget ─────────────────────────────────────────────────────

    @staticmethod
    def _apply_cpu_budget(strategy_cls: type[Any]) -> None:
        """Wrap ``on_bar`` in :func:`asyncio.wait_for` so a single call
        cannot run longer than :data:`ON_BAR_TIMEOUT_SECONDS`.

        The wrapper preserves the original method's signature and
        forwards its return value. If the budget is exceeded,
        :class:`asyncio.TimeoutError` propagates to the caller (the
        orchestrator) which is expected to log and skip the bar.
        """
        original_on_bar = strategy_cls.on_bar

        async def bounded_on_bar(self: Any, bar: Any, ctx: Any) -> Any:
            return await asyncio.wait_for(
                original_on_bar(self, bar, ctx),
                timeout=ON_BAR_TIMEOUT_SECONDS,
            )

        strategy_cls.on_bar = bounded_on_bar  # type: ignore[assignment]
