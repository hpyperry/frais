from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import httpx
from ddgs import DDGS

logger = logging.getLogger(__name__)

_SEARCH_MAX_RESULTS = 5
_FETCH_MAX_CHARS = 5000

_GITHUB_REPO_RE = re.compile(r"github\.com/([^/]+/[^/]+?)(?:\.git)?(?:/|$)")
_VERSION_RE = re.compile(r"\b(\d+\.\d+(?:\.\d+)?(?:\.\d+)?)\b")


def web_search(query: str) -> list[dict[str, str]]:
    """Search the web and return a list of {title, url, snippet}."""
    logger.info("web_search query=%s", query)
    try:
        results = []
        for r in DDGS().text(query, max_results=_SEARCH_MAX_RESULTS):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", ""),
            })
        logger.info("web_search found %d results", len(results))
        return results
    except Exception as exc:
        logger.warning("web_search failed: %s", exc)
        return []


def web_fetch(url: str) -> str:
    """Fetch a URL and return extracted text content."""
    logger.info("web_fetch url=%s", url)
    github_api = _github_url_to_api(url)
    if github_api:
        url = github_api
    try:
        response = httpx.get(
            url,
            headers={
                "User-Agent": "checkupgrade/0.1.0",
                "Accept": "application/vnd.github+json" if "api.github.com" in url else "text/html",
            },
            timeout=httpx.Timeout(8.0, read=15.0),
            follow_redirects=True,
        )
        response.raise_for_status()
        if "api.github.com" in url:
            return _format_github_api(response.json(), url)
        text = _extract_text(response.text)
        if len(text) > _FETCH_MAX_CHARS:
            text = text[:_FETCH_MAX_CHARS] + "\n...<truncated>"
        logger.info("web_fetch got %d chars from %s", len(text), url)
        return text
    except Exception as exc:
        logger.warning("web_fetch failed for %s: %s", url, exc)
        return f"Failed to fetch: {exc}"


def web_fetch_batch(urls: list[str]) -> dict[str, str]:
    """Fetch multiple URLs in parallel and return {url: content}."""
    results: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=min(len(urls), 5)) as pool:
        futures = {pool.submit(web_fetch, url): url for url in urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                results[url] = future.result()
            except Exception as exc:
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
        data = data[0] if data else {}
        return "No releases found."
    if isinstance(data, dict):
        tag = data.get("tag_name") or data.get("name", "")
        body = (data.get("body") or "")[:1500]
        published = data.get("published_at", "")
        return f"Tag: {tag}\nPublished: {published}\nRelease Notes:\n{body}"
    return str(data)[:_FETCH_MAX_CHARS]


TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web. Returns results with title, url, snippet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch_batch",
            "description": "Fetch multiple URLs at once and return their content. Pass a list of URLs to read.",
            "parameters": {
                "type": "object",
                "properties": {
                    "urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of URLs to fetch.",
                    },
                },
                "required": ["urls"],
            },
        },
    },
]

TOOL_HANDLERS: dict[str, Any] = {
    "web_search": web_search,
    "web_fetch": web_fetch,
    "web_fetch_batch": web_fetch_batch,
}


def _extract_text(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
