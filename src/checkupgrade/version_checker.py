from __future__ import annotations

import logging
import re

import httpx

from .models import SoftwareItem, SourceKind

logger = logging.getLogger(__name__)

_ITUNES_SEARCH_URL = "https://itunes.apple.com/lookup"
_GITHUB_API = "https://api.github.com"
_GITHUB_REPO_RE = re.compile(r"github\.com/([^/]+/[^/]+?)(?:\.git)?(?:/|$)")


def check_app_store_version(item: SoftwareItem) -> str | None:
    """Query iTunes API for App Store app latest version."""
    if item.source != SourceKind.APP_STORE:
        return None
    bundle_id = item.id
    if not bundle_id or "." not in bundle_id:
        return None
    try:
        response = httpx.get(
            _ITUNES_SEARCH_URL,
            params={"bundleId": bundle_id, "country": "cn"},
            timeout=httpx.Timeout(5.0, read=10.0),
        )
        response.raise_for_status()
        data = response.json()
        if data.get("resultCount", 0) > 0:
            version = data["results"][0].get("version")
            if version:
                logger.info("itunes version for %s: %s", item.name, version)
                return version
        return None
    except Exception as exc:
        logger.debug("itunes api failed for %s: %s", item.name, exc)
        return None


def check_github_version(repo_url: str) -> str | None:
    """Get latest release version from GitHub API."""
    slug = _extract_github_slug(repo_url)
    if not slug:
        return None
    for endpoint in (f"{_GITHUB_API}/repos/{slug}/releases/latest", f"{_GITHUB_API}/repos/{slug}/tags"):
        try:
            response = httpx.get(
                endpoint,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "checkupgrade"},
                timeout=httpx.Timeout(5.0, read=10.0),
            )
            if response.status_code == 404:
                continue
            response.raise_for_status()
            data = response.json()
            if isinstance(data, list):
                data = data[0] if data else {}
            tag = data.get("tag_name") or data.get("name", "")
            if tag and _is_version_tag(tag):
                return tag.lstrip("vV").strip()
        except Exception as exc:
            logger.debug("github api failed for %s: %s", slug, exc)
    return None


def find_github_repo_from_search(search_results: list[dict[str, str]], app_name: str = "") -> str | None:
    """Extract GitHub repo URL from search results, preferring repos related to app_name."""
    candidates: list[tuple[str, str]] = []
    for r in search_results:
        url = r.get("url", "")
        match = _GITHUB_REPO_RE.search(url)
        if match:
            slug = match.group(1).rstrip("/")
            if "/" in slug and not slug.endswith("/"):
                candidates.append((slug, f"https://github.com/{slug}"))

    if not candidates:
        return None

    # If we have an app name, prefer repos whose name matches
    if app_name:
        name_lower = app_name.lower().replace(" ", "").replace("-", "").replace("_", "")
        for slug, repo_url in candidates:
            repo_name = slug.split("/")[1].lower().replace("-", "").replace("_", "")
            if name_lower in repo_name or repo_name in name_lower:
                logger.info("found matching github repo: %s", repo_url)
                return repo_url

    # Fallback: return first candidate
    _, repo_url = candidates[0]
    logger.info("found github repo from search: %s", repo_url)
    return repo_url


def _extract_github_slug(url: str) -> str | None:
    match = _GITHUB_REPO_RE.search(url)
    if match:
        return match.group(1).rstrip("/")
    return None


_VERSION_TAG_RE = re.compile(r"^v?\d+[\.\-_]\d+")
_NON_VERSION_PATTERNS = re.compile(r"(svn|trunk|nightly|dev|latest|ubuntu|debian|fedora)", re.IGNORECASE)


def _is_version_tag(tag: str) -> bool:
    """Return True if tag looks like a version number, not a branch or CI name."""
    tag = tag.strip()
    if _NON_VERSION_PATTERNS.search(tag):
        return False
    return bool(_VERSION_TAG_RE.match(tag))
