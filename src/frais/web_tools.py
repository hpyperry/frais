import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import cache
from typing import Any

import httpx
from ddgs import DDGS

logger = logging.getLogger(__name__)

_SEARCH_MAX_RESULTS = 5
_FETCH_MAX_CHARS = 5000
_GITHUB_REPO_RE = re.compile(r"github\.com/([^/]+/[^/]+?)(?:\.git)?(?:/|$)")


@cache
def _get_ddgs() -> Any:
    return DDGS()


@cache
def _get_fetch_client() -> Any:
    return httpx.Client(
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/148.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
        },
        timeout=httpx.Timeout(8.0, read=15.0),
        follow_redirects=True,
    )


def web_search(query: str) -> list[dict[str, str]]:
    """Search the web and return a list of title/url/snippet mappings."""
    logger.debug("web_search query=%s", query)
    try:
        results = []
        for result in _get_ddgs().text(query, max_results=_SEARCH_MAX_RESULTS):
            results.append({
                "title": result.get("title", ""),
                "url": result.get("href", ""),
                "snippet": result.get("body", ""),
            })
        logger.debug("web_search found %d results", len(results))
        logger.debug("web_search results=%s", json.dumps(results, ensure_ascii=False)[:2000])
        return results
    except Exception as exc:
        logger.warning("web_search failed: %s", exc, exc_info=True)
        return []


def web_fetch(url: str) -> str:
    """Fetch a URL and return extracted text content."""
    logger.debug("web_fetch url=%s", url)
    resolved_url = _github_url_to_api(url) or url
    try:
        headers: dict[str, str] = {}
        if "api.github.com" in resolved_url:
            headers["Accept"] = "application/vnd.github+json"
        response = _get_fetch_client().get(resolved_url, headers=headers or None)
        response.raise_for_status()
        if "api.github.com" in resolved_url:
            return _format_github_api(response.json(), resolved_url)
        text = _extract_text(response.text)
        if len(text) > _FETCH_MAX_CHARS:
            text = text[:_FETCH_MAX_CHARS] + "\n...<truncated>"
        logger.debug("web_fetch got %d chars from %s", len(text), resolved_url)
        logger.debug("web_fetch content=%s", text[:2000])
        return text
    except Exception as exc:
        logger.warning("web_fetch failed for %s: %s", resolved_url, exc, exc_info=True)
        return f"Failed to fetch: {exc}"


def web_fetch_batch(urls: list[str]) -> dict[str, str]:
    """Fetch multiple URLs in parallel and return a URL-to-content map."""
    results: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=min(len(urls), 5)) as pool:
        futures = {pool.submit(web_fetch, url): url for url in urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                results[url] = future.result()
            except Exception as exc:
                logger.warning("fetch_batch failed url=%s: %s", url, exc, exc_info=True)
                results[url] = f"Failed: {exc}"
    return results


def _github_url_to_api(url: str) -> str | None:
    match = _GITHUB_REPO_RE.search(url)
    if not match:
        return None
    slug = match.group(1).rstrip("/")
    rest = url[match.end():]
    if rest.startswith("/releases") or not rest or rest == "/":
        return f"https://api.github.com/repos/{slug}/releases/latest"
    return None


def _format_github_api(data: Any, url: str) -> str:
    if isinstance(data, list):
        if not data:
            return "No releases found."
        data = data[0]
    if isinstance(data, dict):
        tag = data.get("tag_name") or data.get("name", "")
        body = (data.get("body") or "")[:1500]
        published = data.get("published_at", "")
        return f"Tag: {tag}\nPublished: {published}\nRelease Notes:\n{body}"
    return str(data)[:_FETCH_MAX_CHARS]


def _extract_text(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
