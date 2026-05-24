"""JSON extraction and parsing helpers for LLM outputs."""

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return stripped
    match = re.search(
        r"(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}|\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\])",
        stripped,
        re.DOTALL,
    )
    if match:
        return match.group()
    return stripped


def _parse_json_list(text: str) -> list[str]:
    try:
        data = json.loads(_extract_json(text))
        if isinstance(data, list):
            return [str(item) for item in data if item]
    except (json.JSONDecodeError, TypeError):
        logger.warning("failed to parse JSON list from: %s", text[:200])
    return []


def _parse_json_object(text: str) -> dict[str, Any]:
    try:
        data = json.loads(_extract_json(text))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, TypeError):
        logger.warning("failed to parse JSON object from: %s", text[:200])
    return {}


def _ensure_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if isinstance(value, str):
        return [value]
    return []
