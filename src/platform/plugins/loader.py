"""Plugin loader — discover and register every pluggable extension in ATLAS.

ATLAS is built around five plugin kinds:

* ``strategies``              — trading strategy classes
* ``ai_modules``              — AI analyst modules
* ``risk_rules``              — risk engine rules
* ``execution_adapters``      — broker / exchange connectors
* ``notification_channels``   — email / Telegram / Discord / Slack notifiers

A plugin is discovered in one of three ways:

1. **Built-in** — packages under ``platform.strategies.builtin``,
   ``platform.ai.modules``, ``platform.risk.rules`` that self-register
   via decorators (``@strategy``, etc.) at import time. :meth:`load_builtin`
   walks those packages and imports every submodule.
2. **Entry points** — third-party packages declare an entry point in one
   of the ``atlas.strategies`` / ``atlas.ai_modules`` / ``atlas.risk_rules``
   / ``atlas.execution_adapters`` / ``atlas.notification_channels`` groups.
   The entry point callable accepts no args and registers itself with the
   appropriate registry (either via the loader's :meth:`register` or via
   the subsystem-specific decorator).
3. **Path** — a single ``.py`` file dynamically imported with
   :func:`importlib.util.spec_from_file_location`. Used by the strategy
   sandbox for user-uploaded strategies and by tests.

The loader keeps its own catalog (``kind -> name -> plugin object``) for
:meth:`list_plugins` / :meth:`get_plugin` introspection, and also mirrors
the subsystem-specific registries (StrategyRegistry, AIOrchestrator,
RiskEngine) so the catalog reflects everything that has been registered
via decorators.
"""

from __future__ import annotations

import importlib
import importlib.util
import pkgutil
from pathlib import Path
from platform.core.logging import get_logger
from typing import Any

_log = get_logger(__name__)

# Mapping: entry-point group -> plugin kind handled by this loader.
ENTRY_POINT_GROUPS: dict[str, str] = {
    "atlas.strategies": "strategies",
    "atlas.ai_modules": "ai_modules",
    "atlas.risk_rules": "risk_rules",
    "atlas.execution_adapters": "execution_adapters",
    "atlas.notification_channels": "notification_channels",
}

# Built-in packages to walk during load_builtin(): (kind, dotted package).
BUILTIN_PACKAGES: list[tuple[str, str]] = [
    ("strategies", "platform.strategies.builtin"),
    ("ai_modules", "platform.ai.modules"),
    ("risk_rules", "platform.risk.rules"),
]


class PluginLoader:
    """Discover, load, and catalog every plugin in the platform.

    The loader is intentionally tolerant — a single broken plugin must
    never prevent the rest from loading. Every load operation is wrapped
    in a try/except that logs the failure and continues.
    """

    KINDS: tuple[str, ...] = (
        "strategies",
        "ai_modules",
        "risk_rules",
        "execution_adapters",
        "notification_channels",
    )

    def __init__(self) -> None:
        # kind -> {name -> plugin object/class}
        self._registries: dict[str, dict[str, Any]] = {kind: {} for kind in self.KINDS}
        # Track every module path / dotted name we've already imported so
        # load_*() can be called idempotently.
        self._loaded: set[str] = set()

    # ── Public registration API ────────────────────────────────────────

    def register(self, kind: str, name: str, plugin: Any) -> None:
        """Register a plugin into the loader's catalog.

        Parameters
        ----------
        kind:
            One of :attr:`KINDS`.
        name:
            Unique plugin name within the kind.
        plugin:
            The plugin object — class, instance, factory, depending on kind.

        Raises
        ------
        ValueError
            If ``kind`` is not a recognised plugin kind.
        """
        if kind not in self._registries:
            raise ValueError(f"Unknown plugin kind: {kind!r}. Expected one of {self.KINDS}")
        self._registries[kind][name] = plugin
        _log.info("plugin_registered", kind=kind, name=name)

    def unregister(self, kind: str, name: str) -> None:
        """Remove a plugin from the catalog (no-op if absent)."""
        self._registries.get(kind, {}).pop(name, None)

    # ── Discovery ──────────────────────────────────────────────────────

    def load_builtin(self) -> None:
        """Import every built-in plugin package so they self-register.

        Walks each package listed in :data:`BUILTIN_PACKAGES` with
        :func:`pkgutil.walk_packages` and imports every submodule. The
        submodules use decorators (``@strategy``, etc.) that register
        themselves with the subsystem-specific registries; afterwards we
        mirror those registries into our catalog.

        Safe to call multiple times — already-imported modules are skipped.
        """
        for _kind, package_path in BUILTIN_PACKAGES:
            try:
                package = importlib.import_module(package_path)
            except Exception:
                _log.exception("builtin_package_import_failed", package=package_path)
                continue
            for _finder, mod_name, _is_pkg in pkgutil.walk_packages(
                package.__path__, prefix=f"{package_path}."
            ):
                if mod_name in self._loaded:
                    continue
                try:
                    importlib.import_module(mod_name)
                    self._loaded.add(mod_name)
                    _log.debug("builtin_plugin_loaded", module=mod_name)
                except Exception:
                    _log.exception("builtin_plugin_load_failed", module=mod_name)
        self._mirror_subsystem_registries()

    def load_entry_points(self) -> None:
        """Discover external plugins via :mod:`importlib.metadata`.

        For every entry-point group in :data:`ENTRY_POINT_GROUPS`, loads
        each entry point and invokes its callable. The callable is
        expected to take no arguments and to register itself with the
        appropriate registry (either by calling
        :meth:`PluginLoader.register` or by invoking a subsystem
        decorator like ``@strategy``).
        """
        try:
            from importlib.metadata import entry_points

            eps = entry_points()
        except Exception:
            _log.warning("entry_points_unavailable")
            return

        for group, _kind in ENTRY_POINT_GROUPS.items():
            group_eps = self._select_group(eps, group)
            for ep in group_eps:
                ep_key = f"{group}:{ep.name}"
                if ep_key in self._loaded:
                    continue
                try:
                    fn = ep.load()
                    if callable(fn):
                        fn()
                    self._loaded.add(ep_key)
                    _log.info("entry_point_plugin_loaded", group=group, name=ep.name)
                except Exception:
                    _log.exception(
                        "entry_point_plugin_load_failed",
                        group=group,
                        name=ep.name,
                    )
        self._mirror_subsystem_registries()

    def load_from_path(self, path: Path) -> Any:
        """Dynamically import a single ``.py`` file as a plugin.

        The file is imported under a synthetic module name derived from
        its stem. Any decorators inside the file will self-register with
        the appropriate subsystem registry; we then mirror those into
        the catalog.

        Parameters
        ----------
        path:
            Filesystem path to a ``.py`` file.

        Returns
        -------
        module
            The imported module object (mostly for test convenience).

        Raises
        ------
        ImportError
            If the file cannot be loaded as a Python module.
        """
        path = Path(path).resolve()
        if not path.is_file():
            raise ImportError(f"Plugin file not found: {path}")
        key = str(path)
        if key in self._loaded:
            _log.debug("plugin_path_already_loaded", path=key)
            # Re-import to refresh state — caller may have rewritten the file.
        mod_name = f"_atlas_plugin_{path.stem}"
        spec = importlib.util.spec_from_file_location(mod_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot create module spec for {path}")
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            raise ImportError(f"Failed to execute {path}: {exc}") from exc
        self._loaded.add(key)
        _log.info("plugin_loaded_from_path", path=key, module=mod_name)
        self._mirror_subsystem_registries()
        return module

    # ── Introspection ──────────────────────────────────────────────────

    def list_plugins(self) -> dict[str, list[str]]:
        """Return a mapping ``kind -> [plugin_name, ...]`` for every loaded plugin."""
        return {kind: sorted(reg.keys()) for kind, reg in self._registries.items()}

    def get_plugin(self, kind: str, name: str) -> Any | None:
        """Retrieve a specific plugin by kind and name.

        Returns ``None`` if either the kind or the name is unknown.
        """
        return self._registries.get(kind, {}).get(name)

    @property
    def loaded(self) -> set[str]:
        """Read-only view of every module/entry-point key loaded so far."""
        return set(self._loaded)

    # ── Internals ──────────────────────────────────────────────────────

    @staticmethod
    def _select_group(eps: Any, group: str) -> list[Any]:
        """Compat helper — Python 3.10+ uses ``EntryPoints.select(group=...)``,
        older versions return a dict from ``entry_points()``."""
        # Python 3.12+: EntryPoints supports .select(group=...)
        select = getattr(eps, "select", None)
        if callable(select):
            try:
                return list(select(group=group))
            except TypeError:
                pass
        # Older dict-style API
        if isinstance(eps, dict):
            return list(eps.get(group, []))
        return []

    def _mirror_subsystem_registries(self) -> None:
        """Snapshot the subsystem registries into our own catalog.

        This makes plugins registered via the ``@strategy`` /
        ``AIModule`` / ``RiskRule`` decorators visible through
        :meth:`list_plugins` without forcing every plugin to call
        :meth:`register` explicitly. We use ``setdefault`` so explicit
        registrations made via :meth:`register` are never clobbered.
        """
        # Strategies
        try:
            from platform.strategies.sdk import get_strategy_registry

            strat_reg = get_strategy_registry()
            for name, cls in getattr(strat_reg, "_strategies", {}).items():
                self._registries["strategies"].setdefault(name, cls)
        except Exception:
            _log.debug("strategy_registry_mirror_skipped")

        # AI modules
        try:
            from platform.ai.orchestrator import get_ai_orchestrator

            orch = get_ai_orchestrator()
            for name, mod in getattr(orch, "_modules", {}).items():
                self._registries["ai_modules"].setdefault(name, mod)
        except Exception:
            _log.debug("ai_registry_mirror_skipped")

        # Risk rules
        try:
            from platform.risk.engine import get_risk_engine

            eng = get_risk_engine()
            for rule in getattr(eng, "_rules", []):
                name = getattr(rule, "name", None)
                if name:
                    self._registries["risk_rules"].setdefault(name, rule)
        except Exception:
            _log.debug("risk_registry_mirror_skipped")


# ── Singleton ──────────────────────────────────────────────────────────

_loader: PluginLoader | None = None


def get_plugin_loader() -> PluginLoader:
    """Process-wide singleton accessor for the plugin loader."""
    global _loader
    if _loader is None:
        _loader = PluginLoader()
    return _loader


def load_all_plugins() -> PluginLoader:
    """Convenience helper: load built-in + entry-point plugins in one call."""
    loader = get_plugin_loader()
    loader.load_builtin()
    loader.load_entry_points()
    return loader
