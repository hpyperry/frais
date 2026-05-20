from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import Any

from ...models import DependencyImpact, SoftwareItem, SourceKind, SystemProfile, UpdateCandidate
from ..base import ScannerPlugin

logger = logging.getLogger(__name__)


class HomebrewPlugin(ScannerPlugin):
    name = "homebrew"
    enabled_by_default = True

    def is_available(self) -> bool:
        path = shutil.which("brew")
        logger.debug("homebrew which brew=%s", path or "-")
        return path is not None

    def scan(self, system: SystemProfile) -> tuple[list[UpdateCandidate], list[str]]:
        if not self.is_available():
            logger.info("homebrew unavailable")
            return [], ["Homebrew is not installed or `brew` is not on PATH."]
        try:
            logger.info("homebrew scan outdated start")
            raw = _run_json(["brew", "outdated", "--json=v2"])
        except RuntimeError as exc:
            logger.warning("homebrew outdated failed error=%s", exc)
            return [], [str(exc)]

        candidates: list[UpdateCandidate] = []
        formulae = raw.get("formulae", [])
        casks = raw.get("casks", [])
        logger.info("homebrew outdated formulae=%d casks=%d", len(formulae), len(casks))
        for formula in formulae:
            candidates.append(self._formula_candidate(formula))
        for cask in casks:
            candidates.append(self._cask_candidate(cask))
        return candidates, []

    def _formula_candidate(self, formula: dict[str, Any]) -> UpdateCandidate:
        name = formula.get("name") or "unknown"
        current = _first(formula.get("installed_versions")) or formula.get("installed_version")
        latest = formula.get("current_version") or formula.get("latest_version")
        logger.info("homebrew formula candidate name=%s current=%s latest=%s", name, current or "unknown", latest or "unknown")
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
            risk_level=impact.impact_level,
            recommended_action="Update",
            can_auto_update=True,
            command=["brew", "upgrade", name],
            evidence=[value for value in [info.get("homepage")] if value],
        )

    def _cask_candidate(self, cask: dict[str, Any]) -> UpdateCandidate:
        name = cask.get("name") or cask.get("token") or "unknown"
        current = _first(cask.get("installed_versions")) or cask.get("installed_version")
        latest = cask.get("current_version") or cask.get("latest_version")
        logger.info("homebrew cask candidate name=%s current=%s latest=%s", name, current or "unknown", latest or "unknown")
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
            risk_level="low",
            recommended_action="Review",
            can_auto_update=True,
            command=["brew", "upgrade", "--cask", name],
            evidence=[value for value in [info.get("homepage")] if value],
        )


def _run_json(command: list[str]) -> dict[str, Any]:
    logger.debug("homebrew run command=%s", " ".join(command))
    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=60)
    logger.debug("homebrew command returncode=%s stdout_bytes=%d stderr_bytes=%d", result.returncode, len(result.stdout), len(result.stderr))
    if result.returncode not in {0, 1}:
        raise RuntimeError(result.stderr.strip() or f"Command failed: {' '.join(command)}")
    if not result.stdout.strip():
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON from {' '.join(command)}") from exc


def _brew_info(name: str, cask: bool = False) -> dict[str, Any]:
    command = ["brew", "info", "--json=v2"]
    if cask:
        command.append("--cask")
    command.append(name)
    try:
        data = _run_json(command)
    except RuntimeError:
        logger.warning("homebrew info failed name=%s cask=%s", name, cask)
        return {}
    section = "casks" if cask else "formulae"
    items = data.get(section, [])
    return items[0] if items else {}


def _brew_uses(name: str) -> list[str]:
    logger.debug("homebrew run command=brew uses --installed %s", name)
    result = subprocess.run(
        ["brew", "uses", "--installed", name],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        logger.debug("homebrew uses failed name=%s returncode=%s", name, result.returncode)
        return []
    return sorted(token for token in result.stdout.split() if token)


def _first(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value
