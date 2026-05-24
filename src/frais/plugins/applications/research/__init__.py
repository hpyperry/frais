"""LLM-powered version research pipeline (3-step structured research)."""
from .candidate_factory import _make_candidate
from .json_parser import _ensure_list, _extract_json, _parse_json_list, _parse_json_object
from .pipeline import (
    _llm_structured_research,
    extract_version,
    generate_search_queries,
    pick_urls,
    research_application_update,
)
from .prompts import _EXTRACT_VERSION_PROMPT, _PICK_URLS_PROMPT, _SEARCH_QUERIES_PROMPT
from .version_compare import _digits_only, _is_newer, _normalize

__all__ = [
    "research_application_update",
    "_llm_structured_research",
    "generate_search_queries",
    "pick_urls",
    "extract_version",
    "_extract_json",
    "_parse_json_list",
    "_parse_json_object",
    "_ensure_list",
    "_make_candidate",
    "_is_newer",
    "_normalize",
    "_digits_only",
    "_SEARCH_QUERIES_PROMPT",
    "_PICK_URLS_PROMPT",
    "_EXTRACT_VERSION_PROMPT",
]
