from __future__ import annotations

import logging

import httpx

from ...models import SoftwareItem, SourceKind

logger = logging.getLogger(__name__)

_ITUNES_SEARCH_URL = "https://itunes.apple.com/lookup"


def check_app_store_version(item: SoftwareItem) -> tuple[str | None, int | None]:
    """Query iTunes API for App Store app latest version and track ID.

    Returns (version, track_id). Both are None if not found.
    """
    if item.source != SourceKind.APP_STORE:
        return None, None
    bundle_id = item.id
    if not bundle_id or "." not in bundle_id:
        return None, None
    try:
        response = httpx.get(
            _ITUNES_SEARCH_URL,
            params={"bundleId": bundle_id, "country": "cn"},
            timeout=httpx.Timeout(5.0, read=10.0),
        )
        response.raise_for_status()
        data = response.json()
        if data.get("resultCount", 0) > 0:
            result = data["results"][0]
            version = result.get("version")
            track_id = result.get("trackId")
            if version:
                logger.info("itunes version for %s: %s (trackId=%s)", item.name, version, track_id)
                return version, track_id
        return None, None
    except Exception as exc:
        logger.warning("itunes api failed for %s: %s", item.name, exc)
        return None, None


def resolve_app_store_command(item: SoftwareItem) -> tuple[list[str], bool]:
    """Try to get App Store trackId and return (command, can_auto_update)."""
    try:
        response = httpx.get(
            _ITUNES_SEARCH_URL,
            params={"bundleId": item.id, "country": "cn"},
            timeout=httpx.Timeout(5.0, read=10.0),
        )
        response.raise_for_status()
        data = response.json()
        if data.get("resultCount", 0) > 0:
            track_id = data["results"][0].get("trackId")
            if track_id:
                return ["open", f"macappstore://apps.apple.com/app/id{track_id}"], True
    except Exception as exc:
        logger.debug("itunes lookup failed for %s: %s", item.name, exc)
    return [], False
