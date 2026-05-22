from __future__ import annotations

import logging
import shutil
from typing import Any, Callable

from ...models import DependencyImpact, PluginScanResult, SoftwareItem, SourceKind, SystemProfile, UpdateCandidate
from .._utils import run_json
from ..base import ScannerPlugin

logger = logging.getLogger(__name__)


class NpmPlugin(ScannerPlugin):
    name = "npm"
    enabled_by_default = True
    display_color = "bright_magenta"
    scan_steps = ["checking outdated packages"]

    def is_available(self) -> bool:
        path = shutil.which("npm")
        logger.debug("npm which npm=%s", path or "-")
        return path is not None

    def scan(self, system: SystemProfile,
             on_progress: Callable[[int, int], None] | None = None,
             max_workers: int = 10) -> PluginScanResult:
        if not self.is_available():
            logger.info("npm unavailable")
            return PluginScanResult(skipped=["npm is not installed or `npm` is not on PATH."])
        try:
            logger.info("npm scan outdated start")
            raw = run_json(["npm", "outdated", "-g", "--json"], ok_codes=(0, 1))
        except RuntimeError as exc:
            logger.warning("npm outdated failed error=%s", exc)
            return PluginScanResult(skipped=[str(exc)])

        if not raw:
            logger.info("npm no outdated packages")
            return PluginScanResult()

        candidates, items = self._parse_outdated(raw)
        logger.info("npm outdated items=%d", len(items))
        if on_progress:
            on_progress(0, len(items))
        return PluginScanResult(items=items, candidates=candidates)

    def scan_all(self, system: SystemProfile,
                 on_progress: Callable[[int, int], None] | None = None,
                 max_workers: int = 10) -> PluginScanResult:
        if not self.is_available():
            logger.info("npm unavailable")
            return PluginScanResult(skipped=["npm is not installed or `npm` is not on PATH."])
        try:
            logger.info("npm scan all start")
            installed_raw = run_json(["npm", "ls", "-g", "--depth=0", "--json"])
            outdated_raw = run_json(["npm", "outdated", "-g", "--json"], ok_codes=(0, 1))
        except RuntimeError as exc:
            logger.warning("npm scan all failed error=%s", exc)
            return PluginScanResult(skipped=[str(exc)])

        candidates, _ = self._parse_outdated(outdated_raw)
        all_items = self._parse_installed(installed_raw)
        logger.info("npm scan all items=%d outdated=%d", len(all_items), len(candidates))
        if on_progress:
            on_progress(0, len(all_items))
        return PluginScanResult(items=all_items, candidates=candidates)

    def _parse_outdated(self, raw: dict[str, Any]) -> tuple[list[UpdateCandidate], list[SoftwareItem]]:
        candidates: list[UpdateCandidate] = []
        items: list[SoftwareItem] = []
        for name, info in raw.items():
            cand = self._make_candidate(name, info)
            candidates.append(cand)
            items.append(cand.item)
        return candidates, items

    def _parse_installed(self, raw: dict[str, Any]) -> list[SoftwareItem]:
        deps = raw.get("dependencies", {})
        items: list[SoftwareItem] = []
        for name, info in deps.items():
            version = info.get("version")
            items.append(SoftwareItem(
                id=f"npm:{name}",
                name=name,
                kind="package",
                source=SourceKind.NPM_GLOBAL,
                current_version=version,
            ))
        return items

    def _make_candidate(self, name: str, info: dict[str, Any]) -> UpdateCandidate:
        current = info.get("current")
        latest = info.get("latest") or info.get("wanted")
        logger.info("npm candidate name=%s current=%s latest=%s", name, current or "unknown", latest or "unknown")
        item = SoftwareItem(
            id=f"npm:{name}",
            name=name,
            kind="package",
            source=SourceKind.NPM_GLOBAL,
            current_version=current,
        )
        return UpdateCandidate(
            item=item,
            latest_version=latest,
            dependency_impact=DependencyImpact(impact_level="low"),
            risk_level="low",
            recommended_action="Update",
            can_auto_update=True,
            command=["npm", "install", "-g", name],
            evidence=[f"https://www.npmjs.com/package/{name}"],
        )
