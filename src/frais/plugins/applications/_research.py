from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from packaging.version import InvalidVersion, Version

from ...llm import LLMClient
from ...models import ResearchResult, SourceKind, SoftwareItem, UpdateCandidate
from ...tools import web_fetch_batch, web_search
from ._store import check_app_store_version

logger = logging.getLogger(__name__)


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
    if result and _is_newer(item.current_version, result.latest_version):
        return _make_candidate(item, result.latest_version, result=result)
    return None


def _llm_structured_research(llm: LLMClient, item: SoftwareItem) -> ResearchResult | None:
    """3-step structured research: LLM generates queries, we search & fetch, LLM extracts version."""
    # Step 1: LLM generates search queries
    try:
        queries = llm.generate_search_queries(item)
    except Exception as exc:
        logger.warning("generate_search_queries failed for %s: %s", item.name, exc)
        return None

    if not queries:
        logger.info("no search queries generated for %s", item.name)
        return None

    logger.info("generated %d queries for %s: %s", len(queries), item.name, queries)

    # Execute all searches in parallel
    all_results: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=len(queries)) as pool:
        futures = [pool.submit(web_search, q) for q in queries]
        for future in as_completed(futures):
            try:
                all_results.extend(future.result())
            except Exception as exc:
                logger.warning("web_search failed: %s", exc)

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
        urls = llm.pick_urls(item, unique_results)
    except Exception as exc:
        logger.warning("pick_urls failed for %s: %s", item.name, exc)
        return None

    if not urls:
        logger.info("no URLs picked for %s", item.name)
        return None

    logger.info("picked %d URLs for %s: %s", len(urls), item.name, urls)

    # Fetch all picked URLs in parallel
    fetched = web_fetch_batch(urls)

    # Step 3: LLM extracts version from fetched content
    try:
        return llm.extract_version(item, fetched)
    except Exception as exc:
        logger.warning("extract_version failed for %s: %s", item.name, exc)
        return None


def _make_candidate(item: SoftwareItem, latest_version: str, result: ResearchResult | None = None, source: str = "llm", app_store_id: int | None = None) -> UpdateCandidate:
    can_auto = item.source not in {SourceKind.LOCAL_BUILD, SourceKind.UNKNOWN}
    action = "Update" if can_auto else "Rebuild" if item.source == SourceKind.LOCAL_BUILD else "Manual check"
    command: list[str] = []
    if item.source == SourceKind.APP_STORE and app_store_id:
        command = ["open", f"macappstore://apps.apple.com/app/id{app_store_id}"]
    elif item.source == SourceKind.HOMEBREW_FORMULA:
        command = ["brew", "upgrade", item.name]
    elif item.source == SourceKind.HOMEBREW_CASK:
        command = ["brew", "upgrade", "--cask", item.name]
    candidate = UpdateCandidate(
        item=item,
        latest_version=latest_version,
        release_notes=result.release_notes if result else None,
        recommended_action=action,
        can_auto_update=bool(command),
        command=command,
        evidence=result.evidence if result else [f"Source: {source}"],
        risk_level="unknown" if (not result or result.confidence != "high") else "low",
    )
    return candidate


def _is_newer(current: str | None, latest: str | None) -> bool:
    if not current or not latest:
        return False
    c = _normalize(current)
    l = _normalize(latest)
    if c == l:
        return False
    try:
        vc, vl = Version(c), Version(l)
        return vl > vc
    except InvalidVersion:
        pass
    c2 = _digits_only(c)
    l2 = _digits_only(l)
    if c2 == l2:
        return False
    try:
        return Version(l2) > Version(c2)
    except InvalidVersion:
        return tuple(int(x) for x in l2.split(".")) > tuple(int(x) for x in c2.split("."))


def _normalize(value: str) -> str:
    v = value.strip().lstrip("vV")
    for sep in (" ", "("):
        idx = v.find(sep)
        if idx > 0:
            v = v[:idx]
    return v


def _digits_only(value: str) -> str:
    return "".join(c for c in value if c.isdigit() or c == ".")
