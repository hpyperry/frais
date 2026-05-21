from __future__ import annotations

import logging
from pathlib import Path

from ...models import PluginScanResult, SoftwareItem, SourceKind, SystemProfile, UpdateCandidate
from ...research import research_application_update
from ...scanners.applications import scan_applications
from ..base import ScannerPlugin

logger = logging.getLogger(__name__)


class ApplicationsPlugin(ScannerPlugin):
    name = "applications"
    enabled_by_default = True
    display_color = "cyan"

    def is_available(self) -> bool:
        return True

    def scan(self, system: SystemProfile) -> PluginScanResult:
        items = scan_applications(system.applications_paths)
        logger.info("applications scan found=%d", len(items))
        return PluginScanResult(items=items, candidates=[], skipped=[])

    def scan_all(self, system: SystemProfile) -> PluginScanResult:
        return self.scan(system)

    def research(self, agent, item: SoftwareItem) -> UpdateCandidate | None:
        """Use the 3-step LLM pipeline to find latest versions."""
        try:
            return research_application_update(agent, item)
        except Exception as exc:
            logger.warning("research failed for %s: %s", item.name, exc)
            return None
