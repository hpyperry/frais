from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from .config import RawLLMConfig
from .models import ResearchResult, SoftwareItem, UpdateCandidate

logger = logging.getLogger(__name__)

_SEARCH_QUERIES_PROMPT = (
    "You are a macOS software update research assistant. "
    "Given an application, generate 2-3 web search queries to find its latest version. "
    "Return ONLY a JSON array of query strings.\n"
    "Example: [\"Keka macOS latest version download\", \"Keka changelog 2026\"]\n"
    "Focus on: official download pages, GitHub releases, changelog pages."
)

_PICK_URLS_PROMPT = (
    "You are a macOS software update research assistant. "
    "Given search results for an application, pick the top 3 URLs most likely to contain "
    "the latest version number. Return ONLY a JSON array of URL strings.\n"
    "Prefer: official download pages, GitHub releases, version history pages.\n"
    "Avoid: forums, blog posts, review sites."
)

_EXTRACT_VERSION_PROMPT = (
    "You are a macOS software update research assistant. "
    "Given web page content, extract the latest version of the application.\n"
    "Return ONLY JSON:\n"
    '{"latest_version":"x.y.z or null","confidence":"high/medium/low/unknown",'
    '"evidence":["..."],"release_notes_url":"...","download_url":"...",'
    '"source_repo_url":"...","release_notes":"..."}'
)

_SUMMARIZE_PROMPT = (
    "Summarize the update recommendation for this software in concise Chinese. "
    "Mention risk, dependency impact, and whether the user should update now. "
    "Do not invent facts beyond the provided evidence."
)


class AgentClient:
    """OpenAI-compatible BYOK client for structured version research."""

    def __init__(self, config: RawLLMConfig) -> None:
        if not config.api_key or not config.base_url or not config.model:
            raise ValueError("LLM config is incomplete.")
        self.config = config

    def generate_search_queries(self, item: SoftwareItem) -> list[str]:
        """Step 1: LLM generates search queries for finding the latest version."""
        prompt = (
            f"App: {item.name}, bundle: {item.id}, "
            f"current: {item.current_version or 'unknown'}, "
            f"source: {item.source.value}."
        )
        text = self._chat(_SEARCH_QUERIES_PROMPT, prompt)
        return _parse_json_list(text)

    def pick_urls(self, item: SoftwareItem, search_results: list[dict[str, str]]) -> list[str]:
        """Step 2: LLM picks the most promising URLs from search results."""
        results_text = json.dumps(
            [{"title": r["title"], "url": r["url"], "snippet": r.get("snippet", "")} for r in search_results],
            ensure_ascii=False,
        )
        prompt = f"App: {item.name}\n\nSearch results:\n{results_text}"
        text = self._chat(_PICK_URLS_PROMPT, prompt)
        return _parse_json_list(text)[:3]

    def extract_version(self, item: SoftwareItem, fetched_content: dict[str, str]) -> ResearchResult:
        """Step 3: LLM extracts version info from fetched page content."""
        content_text = json.dumps(
            [{"url": url, "content": content[:3000]} for url, content in fetched_content.items()],
            ensure_ascii=False,
        )
        prompt = (
            f"App: {item.name}, current version: {item.current_version or 'unknown'}\n\n"
            f"Page contents:\n{content_text}"
        )
        text = self._chat(_EXTRACT_VERSION_PROMPT, prompt)
        data = _parse_json_object(text)
        return ResearchResult(
            latest_version=data.get("latest_version"),
            release_notes_url=data.get("release_notes_url"),
            download_url=data.get("download_url"),
            source_repo_url=data.get("source_repo_url"),
            confidence=data.get("confidence") or "unknown",
            evidence=_ensure_list(data.get("evidence")),
            release_notes=data.get("release_notes"),
        )

    def summarize_candidate(self, candidate: UpdateCandidate) -> str:
        """Generate Chinese-language update summary."""
        prompt = (
            f"{_SUMMARIZE_PROMPT}\n\n"
            f"Candidate: {json.dumps(candidate.to_dict(), ensure_ascii=False)}"
        )
        return self._chat("", prompt)

    def test_connection(self) -> str:
        return self._chat("", "Reply with exactly: ok", max_tokens=64)

    def _chat(self, system: str, user: str, max_tokens: int | None = None) -> str:
        url = chat_completions_url(self.config.base_url)
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        response_data = self._post(url, messages, max_tokens=max_tokens)
        message = response_data["choices"][0]["message"]
        return message.get("content") or message.get("reasoning_content") or ""

    def _post(self, url: str, messages: list[dict[str, Any]], max_tokens: int | None = None) -> dict[str, Any]:
        logger.debug("agent request url=%s model=%s messages=%d", url, self.config.model, len(messages))
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0.2,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if self.config.extra_body:
            payload.update(self.config.extra_body)
        response = httpx.post(
            url,
            headers={"Authorization": f"Bearer {self.config.api_key}"},
            json=payload,
            timeout=httpx.Timeout(15.0, read=300.0),
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LLMRequestError.from_response(exc.response) from exc
        return response.json()


class LLMRequestError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, response_text: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text

    @classmethod
    def from_response(cls, response: httpx.Response) -> "LLMRequestError":
        body = response.text.strip()
        if len(body) > 1200:
            body = body[:1200] + "...<truncated>"
        return cls(
            (
                f"LLM request failed with HTTP {response.status_code} at {response.url}. "
                f"Response body: {body or '<empty>'}"
            ),
            status_code=response.status_code,
            response_text=body,
        )


def chat_completions_url(base_url: str | None) -> str:
    if not base_url:
        raise ValueError("LLM base_url is required.")
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return normalized + "/chat/completions"


def _extract_json(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    if stripped.startswith("{"):
        return stripped
    if stripped.startswith("["):
        return stripped
    match = re.search(r"(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}|\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\])", stripped, re.DOTALL)
    if match:
        return match.group()
    return stripped


def _parse_json_list(text: str) -> list[str]:
    """Parse a JSON array of strings from LLM response."""
    try:
        data = json.loads(_extract_json(text))
        if isinstance(data, list):
            return [str(item) for item in data if item]
    except (json.JSONDecodeError, TypeError):
        logger.warning("failed to parse JSON list from: %s", text[:200])
    return []


def _parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from LLM response."""
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
