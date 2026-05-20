from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import Any

from ...models import DependencyImpact, SoftwareItem, SourceKind, SystemProfile, UpdateCandidate
from ..base import ScannerPlugin

logger = logging.getLogger(__name__)


class NpmPlugin(ScannerPlugin):
    name = "npm"
    enabled_by_default = True

    def is_available(self) -> bool:
        path = shutil.which("npm")
        logger.debug("npm which npm=%s", path or "-")
        return path is not None

    def scan(self, system: SystemProfile) -> tuple[list[UpdateCandidate], list[str]]:
        if not self.is_available():
            logger.info("npm unavailable")
            return [], ["npm is not installed or `npm` is not on PATH."]
        try:
            logger.info("npm scan outdated start")
            raw = _run_json(["npm", "outdated", "-g", "--json"])
        except RuntimeError as exc:
            logger.warning("npm outdated failed error=%s", exc)
            return [], [str(exc)]

        if not raw:
            logger.info("npm no outdated packages")
            return [], []

        logger.info("npm outdated packages=%d", len(raw))
        candidates: list[UpdateCandidate] = []
        for name, info in raw.items():
            candidates.append(self._make_candidate(name, info))
        return candidates, []

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


def _run_json(command: list[str]) -> dict[str, Any]:
    logger.debug("npm run command=%s", " ".join(command))
    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=60)
    logger.debug("npm command returncode=%s stdout_bytes=%d stderr_bytes=%d", result.returncode, len(result.stdout), len(result.stderr))
    # npm outdated returns exit code 1 when there are outdated packages
    if result.returncode not in {0, 1}:
        raise RuntimeError(result.stderr.strip() or f"Command failed: {' '.join(command)}")
    if not result.stdout.strip():
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON from {' '.join(command)}") from exc
