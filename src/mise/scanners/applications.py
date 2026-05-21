from __future__ import annotations

import hashlib
import logging
import plistlib
import subprocess
from pathlib import Path

from ..models import SoftwareItem, SourceKind

logger = logging.getLogger(__name__)


def scan_applications(paths: list[str]) -> list[SoftwareItem]:
    items: list[SoftwareItem] = []
    seen: set[str] = set()
    for base in paths:
        base_path = Path(base).expanduser()
        logger.info("applications scan path=%s exists=%s", base_path, base_path.exists())
        if not base_path.exists():
            continue
        app_paths = sorted(base_path.glob("*.app"))
        logger.info("applications found bundles path=%s count=%d", base_path, len(app_paths))
        for app_path in app_paths:
            logger.debug("applications reading bundle=%s", app_path)
            item = read_application(app_path)
            if not item:
                logger.debug("applications skipped unreadable bundle=%s", app_path)
                continue
            if item.id in seen:
                logger.debug("applications skipped duplicate id=%s path=%s", item.id, app_path)
                continue
            seen.add(item.id)
            logger.info(
                "applications item name=%s id=%s version=%s source=%s",
                item.name,
                item.id,
                item.current_version or "unknown",
                item.source.value,
            )
            items.append(item)
    return items


def read_application(app_path: Path) -> SoftwareItem | None:
    plist_path = app_path / "Contents" / "Info.plist"
    if not plist_path.exists():
        logger.debug("applications missing Info.plist path=%s", plist_path)
        return None
    try:
        with plist_path.open("rb") as handle:
            info = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException):
        logger.debug("applications failed to parse Info.plist path=%s", plist_path, exc_info=True)
        return None

    name = (
        info.get("CFBundleDisplayName")
        or info.get("CFBundleName")
        or app_path.stem
    )
    bundle_id = info.get("CFBundleIdentifier")
    version = info.get("CFBundleShortVersionString") or info.get("CFBundleVersion")
    signing = _signing_summary(app_path)
    quarantine = _quarantine_summary(app_path)
    source = classify_source(bundle_id, signing, quarantine)
    stable_id = bundle_id or _path_id(app_path)
    return SoftwareItem(
        id=stable_id,
        name=str(name),
        kind="application",
        source=source,
        current_version=str(version) if version is not None else None,
        path=str(app_path),
        metadata={
            "bundle_id": bundle_id,
            "signing": signing,
            "quarantine": quarantine,
        },
    )


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
        result = subprocess.run(
            ["codesign", "-dv", "--verbose=4", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
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
        result = subprocess.run(
            ["xattr", "-p", "com.apple.quarantine", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        logger.debug("applications xattr failed path=%s", path, exc_info=True)
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None
