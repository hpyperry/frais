from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from packaging.version import InvalidVersion, Version

from .agent import AgentClient
from .models import ResearchResult, SourceKind, SoftwareItem, UpdateCandidate
from .tools import web_search
from .version_checker import check_app_store_version, check_github_version, find_github_repo_from_search

logger = logging.getLogger(__name__)


def research_application_update(agent: AgentClient, item: SoftwareItem) -> UpdateCandidate | None:
    # Fast path 1: App Store apps via iTunes API
    latest = check_app_store_version(item)
    if latest and _is_newer(item.current_version, latest):
        return _make_candidate(item, latest, source="itunes")
    if latest:
        return None  # Confirmed up to date via iTunes

    # Fast path 2 + Slow path: run GitHub fast path and LLM concurrently
    return _research_concurrent(agent, item)


def _research_concurrent(agent: AgentClient, item: SoftwareItem) -> UpdateCandidate | None:
    """Run GitHub fast path and LLM in parallel; use whichever gives a valid answer first."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        llm_future = pool.submit(agent.research_application, item)
        github_future = pool.submit(_try_github_fast_path, item)

        # Wait for GitHub fast path first (~3s)
        github_version = None
        try:
            github_version = github_future.result(timeout=15)
        except Exception as exc:
            logger.debug("github fast path failed for %s: %s", item.name, exc)

        if github_version:
            llm_future.cancel()
            if _is_newer(item.current_version, github_version):
                return _make_candidate(item, github_version, source="github")
            return None  # Confirmed up to date via GitHub

        # GitHub didn't find anything, wait for LLM
        try:
            result = llm_future.result()
        except Exception as exc:
            logger.warning("LLM research failed for %s: %s", item.name, exc)
            return None

        if not _is_newer(item.current_version, result.latest_version):
            return None
        return _make_candidate(item, result.latest_version, result=result)


def _try_github_fast_path(item: SoftwareItem) -> str | None:
    """Search for a GitHub repo and check its latest release — no LLM involved."""
    query = f"{item.name} macOS latest release github"
    try:
        results = web_search(query)
        repo_url = find_github_repo_from_search(results, app_name=item.name)
        if repo_url:
            version = check_github_version(repo_url)
            if version:
                logger.info("github fast path for %s: %s", item.name, version)
                return version
    except Exception as exc:
        logger.debug("github fast path failed for %s: %s", item.name, exc)
    return None


def _make_candidate(item: SoftwareItem, latest_version: str, result: ResearchResult | None = None, source: str = "llm") -> UpdateCandidate:
    can_auto = item.source not in {SourceKind.LOCAL_BUILD, SourceKind.UNKNOWN}
    action = "Update" if can_auto else "Rebuild" if item.source == SourceKind.LOCAL_BUILD else "Manual check"
    candidate = UpdateCandidate(
        item=item,
        latest_version=latest_version,
        release_notes=result.release_notes if result else None,
        recommended_action=action,
        can_auto_update=False,
        evidence=result.evidence if result else [f"Source: {source}"],
        risk_level="unknown" if (not result or result.confidence != "high") else "low",
    )
    return candidate


def attach_ai_summaries(agent: AgentClient, candidates: list[UpdateCandidate]) -> list[UpdateCandidate]:
    for candidate in candidates:
        candidate.ai_summary = agent.summarize_candidate(candidate)
    return candidates


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
    # Fallback: strip all non-digit/dot chars and compare
    c2 = _digits_only(c)
    l2 = _digits_only(l)
    if c2 == l2:
        return False
    try:
        return Version(l2) > Version(c2)
    except InvalidVersion:
        return l2 != c2


def _normalize(value: str) -> str:
    v = value.strip().lstrip("vV")
    for sep in (" ", "("):
        idx = v.find(sep)
        if idx > 0:
            v = v[:idx]
    return v


def _digits_only(value: str) -> str:
    return "".join(c for c in value if c.isdigit() or c == ".")

