from __future__ import annotations

import logging
from importlib.metadata import entry_points

from .base import ScannerPlugin
from .homebrew import HomebrewPlugin

logger = logging.getLogger(__name__)

_ENTRY_POINT_GROUP = "checkupgrade.plugins"


def all_plugins() -> dict[str, ScannerPlugin]:
    plugins: dict[str, ScannerPlugin] = {"homebrew": HomebrewPlugin()}
    for ep in entry_points(group=_ENTRY_POINT_GROUP):
        try:
            cls = ep.load()
            plugin = cls()
            plugins[plugin.name] = plugin
        except Exception as exc:
            logger.warning("failed to load plugin %s: %s", ep.name, exc)
    return plugins


def enabled_plugins(names: list[str] | None = None) -> list[ScannerPlugin]:
    registry = all_plugins()
    if names:
        return [registry[name] for name in names if name in registry]
    return [plugin for plugin in registry.values() if plugin.enabled_by_default]
