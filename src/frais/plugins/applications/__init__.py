from __future__ import annotations

import hashlib
import logging
import os
import plistlib
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from ...models import PluginScanResult, SoftwareItem, SourceKind, SystemProfile, UpdateCandidate
from ..base import ScannerPlugin
from ._research import research_application_update
from ._store import resolve_app_store_command

logger = logging.getLogger(__name__)


class ApplicationsPlugin(ScannerPlugin):
    name = "applications"
    enabled_by_default = True
    display_color = "cyan"
    scan_steps = ["discovering apps", "researching latest versions"]

    def is_available(self) -> bool:
        return True

    def scan(self, system: SystemProfile,
             on_progress: Callable[[int, int, int], None] | None = None,
             max_workers: int = 10) -> PluginScanResult:
        # Step 1: discover all installed applications
        items = scan_applications(system.applications_paths)
        logger.info("applications scan found=%d", len(items))
        if on_progress:
            on_progress(0, len(items), len(items))

        # Step 2: research latest versions for non-App-Store apps
        from ...config import require_config
        from ...llm import get_client

        try:
            config = require_config()
            llm = get_client(config)
        except (ValueError, RuntimeError) as exc:
            logger.warning("LLM not available for applications research: %s", exc)
            return PluginScanResult(items=items, candidates=[], skipped=[str(exc)])

        candidates: list[UpdateCandidate] = []
        to_research = [it for it in items if it.source != SourceKind.APP_STORE]
        researched = 0

        if on_progress:
            on_progress(1, 0, len(to_research))

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(research_application_update, llm, it): it for it in to_research}
            for future in as_completed(futures):
                researched += 1
                try:
                    candidate = future.result()
                except Exception as exc:
                    logger.warning("research failed: %s", exc, exc_info=True)
                    if on_progress:
                        on_progress(1, researched, len(to_research))
                    continue
                if candidate:
                    candidates.append(candidate)
                if on_progress:
                    on_progress(1, researched, len(to_research))

        logger.info("applications research done candidates=%d", len(candidates))
        llm.close()
        return PluginScanResult(items=items, candidates=candidates)

    def update(self, candidate: UpdateCandidate) -> bool:
        import typer

        if candidate.item.source == SourceKind.APP_STORE:
            cmd, can_auto = resolve_app_store_command(candidate.item)
            if can_auto and cmd:
                subprocess.run(cmd, check=False)
                return True
        if candidate.can_auto_update and candidate.command:
            return super().update(candidate)
        if candidate.item.path:
            if typer.confirm("    Open app for manual update?", default=False):
                subprocess.run(["open", candidate.item.path], check=False)
                return True
            return False
        return False


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
