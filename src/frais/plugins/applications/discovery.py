from __future__ import annotations

import logging
import plistlib
from pathlib import Path

from ...models import SoftwareItem
from .source_classifier import _path_id, _quarantine_summary, _signing_summary, classify_source

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
