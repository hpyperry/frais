"""3-step structured LLM research pipeline for application version discovery."""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from ....llm import LLMClient
from ....models import ResearchResult, SoftwareItem, UpdateCandidate
from ....web_tools import web_fetch_batch, web_search
from ..app_store import check_app_store_version
from .candidate_factory import _make_candidate
from .json_parser import _ensure_list, _parse_json_list, _parse_json_object
from .prompts import _EXTRACT_VERSION_PROMPT, _PICK_URLS_PROMPT, _SEARCH_QUERIES_PROMPT
from .version_compare import _is_newer

logger = logging.getLogger(__name__)


def generate_search_queries(llm: LLMClient, item: SoftwareItem) -> list[str]:
    """Step 1: generate search queries for finding the latest version."""
    prompt = (
        f"App: {item.name}, bundle: {item.id}, "
        f"current: {item.current_version or 'unknown'}, "
        f"source: {item.source.value}."
    )
    logger.debug("step1 prompt for %s: %s", item.name, prompt)
    text = llm.chat(_SEARCH_QUERIES_PROMPT, prompt, disable_thinking=True)
    logger.debug("step1 response for %s: %s", item.name, text)
    return _parse_json_list(text)


def pick_urls(llm: LLMClient, item: SoftwareItem, search_results: list[dict[str, str]]) -> list[str]:
    """Step 2: pick the most promising URLs from search results."""
    results_text = json.dumps(
        [{"title": r["title"], "url": r["url"], "snippet": r.get("snippet", "")} for r in search_results],
        ensure_ascii=False,
    )
    prompt = f"App: {item.name}\n\nSearch results:\n{results_text}"
    logger.debug("step2 input for %s: %s", item.name, results_text[:2000])
    text = llm.chat(_PICK_URLS_PROMPT, prompt, disable_thinking=True)
    logger.debug("step2 response for %s: %s", item.name, text)
    return _parse_json_list(text)[:3]


def extract_version(llm: LLMClient, item: SoftwareItem, fetched_content: dict[str, str]) -> ResearchResult:
    """Step 3: extract version info from fetched page content."""
    content_text = json.dumps(
        [{"url": url, "content": content[:3000]} for url, content in fetched_content.items()],
        ensure_ascii=False,
    )
    prompt = (
        f"App: {item.name}, current version: {item.current_version or 'unknown'}\n\n"
        f"Page contents:\n{content_text}"
    )
    logger.debug("step3 input for %s: %s", item.name, content_text[:2000])
    text = llm.chat(_EXTRACT_VERSION_PROMPT, prompt, disable_thinking=True)
    logger.debug("step3 response for %s: %s", item.name, text)
    data = _parse_json_object(text)
    logger.debug("step3 result for %s: %s", item.name, data)
    return ResearchResult(
        latest_version=data.get("latest_version"),
        release_notes_url=data.get("release_notes_url"),
        download_url=data.get("download_url"),
        source_repo_url=data.get("source_repo_url"),
        confidence=data.get("confidence") or "unknown",
        evidence=_ensure_list(data.get("evidence")),
        release_notes=data.get("release_notes"),
    )


def research_application_update(llm: LLMClient, item: SoftwareItem) -> UpdateCandidate | None:
    """Research latest version for an application using three-tier strategy."""
    # Tier 1: App Store apps via iTunes API (~1s)
    latest, track_id = check_app_store_version(item)
    if latest and _is_newer(item.current_version, latest):
        return _make_candidate(item, latest, source="itunes", app_store_id=track_id)
    if latest:
        return None  # Confirmed up to date via iTunes

    # Tier 2: LLM-driven structured research (generate queries -> search -> pick URLs -> extract)
    result = _llm_structured_research(llm, item)
    if result and result.latest_version and _is_newer(item.current_version, result.latest_version):
        return _make_candidate(item, result.latest_version, result=result)
    return None


def _llm_structured_research(llm: LLMClient, item: SoftwareItem) -> ResearchResult | None:
    """3-step structured research: LLM generates queries, we search & fetch, LLM extracts version."""
    # Step 1: LLM generates search queries
    try:
        queries = generate_search_queries(llm, item)
    except Exception as exc:
        logger.warning("generate_search_queries failed for %s: %s", item.name, exc, exc_info=True)
        return None

    if not queries:
        logger.info("no search queries generated for %s", item.name)
        return None

    logger.info("generated %d queries for %s", len(queries), item.name)
    logger.debug("queries for %s: %s", item.name, queries)

    # Execute all searches in parallel
    all_results: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=len(queries)) as pool:
        futures = [pool.submit(web_search, q) for q in queries]
        for future in as_completed(futures):
            try:
                all_results.extend(future.result())
            except Exception as exc:
                logger.warning("web_search failed for %s: %s", item.name, exc, exc_info=True)

    # Deduplicate by URL
    seen_urls: set[str] = set()
    unique_results: list[dict[str, str]] = []
    for r in all_results:
        url = r.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_results.append(r)

    if not unique_results:
        logger.info("no search results for %s", item.name)
        return None

    logger.info("found %d unique search results for %s", len(unique_results), item.name)

    # Step 2: LLM picks best URLs
    try:
        urls = pick_urls(llm, item, unique_results)
    except Exception as exc:
        logger.warning("pick_urls failed for %s: %s", item.name, exc, exc_info=True)
        return None

    if not urls:
        logger.info("no URLs picked for %s", item.name)
        return None

    logger.info("picked %d URLs for %s", len(urls), item.name)
    logger.debug("urls for %s: %s", item.name, urls)

    # Fetch all picked URLs in parallel
    fetched = web_fetch_batch(urls)

    # Step 3: LLM extracts version from fetched content
    try:
        return extract_version(llm, item, fetched)
    except Exception as exc:
        logger.warning("extract_version failed for %s: %s", item.name, exc, exc_info=True)
        return None
