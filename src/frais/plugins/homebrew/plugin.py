from __future__ import annotations

import logging
import os
import shutil
import subprocess
from collections.abc import Callable
from typing import Any

from ...models import (
    DependencyImpact,
    PluginScanResult,
    SoftwareItem,
    SourceKind,
    SystemProfile,
    UpdateCandidate,
)
from ..base import ScannerPlugin
from ..subprocess_json import run_json

logger = logging.getLogger(__name__)


class HomebrewPlugin(ScannerPlugin):
    name = "homebrew"
    enabled_by_default = True
    display_color = "orange3"
    scan_steps = ["checking outdated packages"]

    def is_available(self) -> bool:
        path = shutil.which("brew")
        logger.debug("homebrew which brew=%s", path or "-")
        return path is not None

    def scan(self, system: SystemProfile,
             on_progress: Callable[[int, int, int], None] | None = None,
             max_workers: int = 10) -> PluginScanResult:
        if not self.is_available():
            logger.info("homebrew unavailable")
            return PluginScanResult(skipped=["Homebrew is not installed or `brew` is not on PATH."])
        try:
            logger.info("homebrew scan outdated start")
            raw = run_json(["brew", "outdated", "--json=v2"], ok_codes=(0, 1))
        except RuntimeError as exc:
            logger.warning("homebrew outdated failed error=%s", exc)
            return PluginScanResult(skipped=[str(exc)])

        candidates, items = self._parse_outdated(raw)
        logger.info("homebrew outdated items=%d", len(items))
        if on_progress:
            on_progress(0, len(items), len(items))
        return PluginScanResult(items=items, candidates=candidates)

    def scan_all(self, system: SystemProfile,
                 on_progress: Callable[[int, int, int], None] | None = None,
                 max_workers: int = 10) -> PluginScanResult:
        if not self.is_available():
            logger.info("homebrew unavailable")
            return PluginScanResult(skipped=["Homebrew is not installed or `brew` is not on PATH."])
        try:
            logger.info("homebrew scan all start")
            installed_raw = run_json(["brew", "info", "--json=v2", "--installed"])
            outdated_raw = run_json(["brew", "outdated", "--json=v2"], ok_codes=(0, 1))
        except RuntimeError as exc:
            logger.warning("homebrew scan all failed error=%s", exc)
            return PluginScanResult(skipped=[str(exc)])

        candidates, _ = self._parse_outdated(outdated_raw)
        all_items = self._parse_installed(installed_raw)
        logger.info("homebrew scan all items=%d outdated=%d", len(all_items), len(candidates))
        if on_progress:
            on_progress(0, len(all_items), len(all_items))
        return PluginScanResult(items=all_items, candidates=candidates)

    def _parse_outdated(self, raw: dict[str, Any]) -> tuple[list[UpdateCandidate], list[SoftwareItem]]:
        candidates: list[UpdateCandidate] = []
        items: list[SoftwareItem] = []
        for formula in raw.get("formulae", []):
            cand = self._formula_candidate(formula)
            candidates.append(cand)
            items.append(cand.item)
        for cask in raw.get("casks", []):
            cand = self._cask_candidate(cask)
            candidates.append(cand)
            items.append(cand.item)
        return candidates, items

    def _parse_installed(self, raw: dict[str, Any]) -> list[SoftwareItem]:
        items: list[SoftwareItem] = []
        for formula in raw.get("formulae", []):
            name = formula.get("name") or "unknown"
            current = formula.get("linked_keg") or _installed_version(formula)
            items.append(SoftwareItem(
                id=f"brew:{name}",
                name=name,
                kind="package",
                source=SourceKind.HOMEBREW_FORMULA,
                current_version=current,
            ))
        for cask in raw.get("casks", []):
            name = cask.get("name") or cask.get("token") or "unknown"
            current = _cask_current_version(cask)
            items.append(SoftwareItem(
                id=f"brew-cask:{name}",
                name=name,
                kind="application",
                source=SourceKind.HOMEBREW_CASK,
                current_version=current,
            ))
        return items

    def _formula_candidate(self, formula: dict[str, Any]) -> UpdateCandidate:
        name = formula.get("name") or "unknown"
        current = _first(formula.get("installed_versions")) or formula.get("installed_version")
        latest = formula.get("current_version") or formula.get("latest_version")
        logger.info("homebrew formula candidate name=%s current=%s latest=%s",
                    name, current or "unknown", latest or "unknown")
        info = _brew_info(name)
        depends_on = sorted(set(info.get("dependencies", []) + info.get("runtime_dependencies", [])))
        used_by = _brew_uses(name)
        impact = DependencyImpact(
            used_by=used_by,
            depends_on=depends_on,
            impact_level="medium" if used_by else "low",
        )
        item = SoftwareItem(
            id=f"brew:{name}",
            name=name,
            kind="package",
            source=SourceKind.HOMEBREW_FORMULA,
            current_version=str(current) if current else None,
            metadata={"homebrew": info},
        )
        return UpdateCandidate(
            item=item,
            latest_version=str(latest) if latest else None,
            dependency_impact=impact,
            can_auto_update=True,
            command=["brew", "upgrade", name],
            evidence=[value for value in [info.get("homepage")] if value],
        )

    def _cask_candidate(self, cask: dict[str, Any]) -> UpdateCandidate:
        name = cask.get("name") or cask.get("token") or "unknown"
        current = _first(cask.get("installed_versions")) or cask.get("installed_version")
        latest = cask.get("current_version") or cask.get("latest_version")
        logger.info("homebrew cask candidate name=%s current=%s latest=%s",
                    name, current or "unknown", latest or "unknown")
        info = _brew_info(name, cask=True)
        item = SoftwareItem(
            id=f"brew-cask:{name}",
            name=name,
            kind="application",
            source=SourceKind.HOMEBREW_CASK,
            current_version=str(current) if current else None,
            metadata={"homebrew": info},
        )
        return UpdateCandidate(
            item=item,
            latest_version=str(latest) if latest else None,
            dependency_impact=DependencyImpact(impact_level="low"),
            can_auto_update=True,
            command=["brew", "upgrade", "--cask", name],
            evidence=[value for value in [info.get("homepage")] if value],
        )


def _brew_info(name: str, cask: bool = False) -> dict[str, Any]:
    command = ["brew", "info", "--json=v2"]
    if cask:
        command.append("--cask")
    command.append(name)
    try:
        data = run_json(command)
    except RuntimeError:
        logger.warning("homebrew info failed name=%s cask=%s", name, cask)
        return {}
    section = "casks" if cask else "formulae"
    items = data.get(section, [])
    return items[0] if items else {}


def _brew_uses(name: str) -> list[str]:
    logger.debug("homebrew run command=brew uses --installed %s", name)
    env = os.environ.copy()
    env.pop("DYLD_LIBRARY_PATH", None)
    try:
        result = subprocess.run(
            ["brew", "uses", "--installed", name],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
    except subprocess.TimeoutExpired:
        logger.debug("homebrew uses timed out name=%s", name)
        return []
    if result.returncode != 0:
        logger.debug("homebrew uses failed name=%s returncode=%s", name, result.returncode)
        return []
    return sorted(token for token in result.stdout.split() if token)


def _first(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _installed_version(pkg: dict[str, Any]) -> str | None:
    linked: Any = pkg.get("linked_keg")
    if linked:
        return str(linked)
    installed_list: Any = pkg.get("installed")
    if isinstance(installed_list, list) and installed_list:
        return str(installed_list[0].get("version")) if installed_list[0].get("version") else None
    return None


def _cask_current_version(cask: dict[str, Any]) -> str | None:
    linked: Any = cask.get("linked_keg")
    if linked:
        return str(linked)
    version: Any = cask.get("version")
    return str(version) if version else None
