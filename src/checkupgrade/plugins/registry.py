from __future__ import annotations

from .base import ScannerPlugin
from .homebrew import HomebrewPlugin


def all_plugins() -> dict[str, ScannerPlugin]:
    plugins: list[ScannerPlugin] = [HomebrewPlugin()]
    return {plugin.name: plugin for plugin in plugins}


def enabled_plugins(names: list[str] | None = None) -> list[ScannerPlugin]:
    registry = all_plugins()
    if names:
        return [registry[name] for name in names if name in registry]
    return [plugin for plugin in registry.values() if plugin.enabled_by_default]
