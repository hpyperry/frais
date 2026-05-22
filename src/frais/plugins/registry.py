from __future__ import annotations

import logging
from importlib.metadata import entry_points

from .base import ScannerPlugin

logger = logging.getLogger(__name__)

_ENTRY_POINT_GROUP = "frais.plugins"


def all_plugins() -> dict[str, ScannerPlugin]:
    plugins: dict[str, ScannerPlugin] = {}
    for ep in entry_points(group=_ENTRY_POINT_GROUP):
        try:
            cls = ep.load()
            plugin = cls()
            plugins[plugin.name] = plugin
        except Exception as exc:
            logger.warning("failed to load plugin %s: %s", ep.name, exc)
    return plugins
