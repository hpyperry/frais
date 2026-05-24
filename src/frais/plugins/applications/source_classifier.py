from __future__ import annotations

import hashlib
import logging
import os
import subprocess
from pathlib import Path

from ...models import SourceKind

logger = logging.getLogger(__name__)


def classify_source(
    bundle_id: str | None,
    signing: dict[str, str | None],
    quarantine: str | None,
) -> SourceKind:
    if signing.get("authority") == "Apple Mac OS Application Signing":
        return SourceKind.APP_STORE
    if signing.get("team_id") in {None, "-"} and signing.get("authority") in {None, "adhoc"}:
        return SourceKind.LOCAL_BUILD
    if quarantine and any(token in quarantine.lower() for token in ("http", "https", "safari", "chrome")):
        return SourceKind.NETWORK_DOWNLOAD
    if bundle_id:
        return SourceKind.APPLICATION
    return SourceKind.UNKNOWN


def _path_id(path: Path) -> str:
    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]
    return f"app:{digest}"


def _signing_summary(path: Path) -> dict[str, str | None]:
    try:
        logger.debug("applications running codesign path=%s", path)
        env = os.environ.copy()
        env.pop("DYLD_LIBRARY_PATH", None)
        result = subprocess.run(
            ["codesign", "-dv", "--verbose=4", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        logger.debug("applications codesign failed path=%s", path, exc_info=True)
        return {"authority": None, "team_id": None}

    output = f"{result.stdout}\n{result.stderr}"
    authority = None
    team_id = None
    for line in output.splitlines():
        if line.startswith("Authority=") and authority is None:
            authority = line.split("=", 1)[1].strip()
        elif line.startswith("TeamIdentifier="):
            team_id = line.split("=", 1)[1].strip()
    if result.returncode != 0 and authority is None:
        authority = "adhoc"
    return {"authority": authority, "team_id": team_id}


def _quarantine_summary(path: Path) -> str | None:
    try:
        logger.debug("applications reading quarantine xattr path=%s", path)
        env = os.environ.copy()
        env.pop("DYLD_LIBRARY_PATH", None)
        result = subprocess.run(
            ["xattr", "-p", "com.apple.quarantine", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        logger.debug("applications xattr failed path=%s", path, exc_info=True)
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None
