from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from .llm import LLMClient
from .models import UpdateCandidate

logger = logging.getLogger(__name__)


def generate_summaries(llm: LLMClient, candidates: list[UpdateCandidate],
                       max_workers: int = 5,
                       progress: object | None = None,
                       task_id: object | None = None) -> None:
    """Generate AI summaries for all candidates concurrently."""
    if not candidates:
        return
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_summarize_one, llm, c) for c in candidates]
        for future in as_completed(futures):
            future.result()
            if progress is not None and task_id is not None:
                progress.advance(task_id)


def _summarize_one(llm: LLMClient, candidate: UpdateCandidate) -> None:
    try:
        candidate.ai_summary = llm.summarize_candidate(candidate)
    except Exception as exc:
        logger.warning("summary failed for %s: %s", candidate.item.name, exc)
