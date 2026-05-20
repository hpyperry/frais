from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from .config import RawLLMConfig
from .models import ResearchResult, SoftwareItem, UpdateCandidate
from .tools import TOOL_HANDLERS, TOOLS

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Find the latest version of a macOS app. You have web_search and web_fetch_batch.\n"
    "STEPS: 1) web_search once 2) web_fetch_batch with 1-2 best URLs at once 3) return JSON.\n"
    "Max 2 tool calls. Use web_fetch_batch (not web_fetch) to fetch multiple URLs in one call.\n"
    "Return ONLY JSON:\n"
    '{"latest_version":"x.y.z or null","confidence":"high/medium/low/unknown",'
    '"evidence":["..."],"release_notes_url":"...","download_url":"...",'
    '"source_repo_url":"...","release_notes":"..."}'
)

_MAX_TOOL_ROUNDS = 4


class AgentClient:
    """OpenAI-compatible BYOK client with tool calling for web search."""

    def __init__(self, config: RawLLMConfig) -> None:
        if not config.api_key or not config.base_url or not config.model:
            raise ValueError("LLM config is incomplete.")
        self.config = config

    def research_application(self, item: SoftwareItem) -> ResearchResult:
        logger.info("agent research application name=%s id=%s version=%s", item.name, item.id, item.current_version or "unknown")
        prompt = (
            f"App: {item.name}, bundle: {item.id}, current: {item.current_version or 'unknown'}, "
            f"source: {item.source.value}. Find its latest version online."
        )
        data = self._chat_with_tools(prompt)
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
        logger.info("agent summarize candidate name=%s latest=%s", candidate.item.name, candidate.latest_version or "unknown")
        prompt = (
            "Summarize the update recommendation for this software in concise Chinese. "
            "Mention risk, dependency impact, and whether the user should update now. "
            "Do not invent facts beyond the provided evidence.\n\n"
            f"Candidate: {json.dumps(candidate.to_dict(), ensure_ascii=False)}"
        )
        return self._chat(prompt)

    def test_connection(self) -> str:
        return self._chat("Reply with exactly: ok", max_tokens=64)

    def _chat_with_tools(self, prompt: str) -> dict[str, Any]:
        """Chat loop with tool calling support."""
        url = chat_completions_url(self.config.base_url)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        for round_num in range(_MAX_TOOL_ROUNDS):
            logger.debug("agent tool round=%d messages=%d", round_num + 1, len(messages))
            response_data = self._post(url, messages, tools=TOOLS)
            choice = response_data["choices"][0]
            message = choice["message"]
            # If no tool calls, we have the final answer
            if not message.get("tool_calls"):
                text = message.get("content") or message.get("reasoning_content") or ""
                logger.debug("agent final response text=%s", text[:500])
                try:
                    return json.loads(_extract_json(text))
                except json.JSONDecodeError:
                    logger.warning("agent response was not valid json: %s", text[:300])
                    return {"latest_version": None, "confidence": "unknown", "evidence": ["LLM response was not valid JSON."]}
            # Execute tool calls
            messages.append(message)
            for tool_call in message["tool_calls"]:
                fn_name = tool_call["function"]["name"]
                try:
                    fn_args = json.loads(tool_call["function"]["arguments"])
                except json.JSONDecodeError:
                    fn_args = {}
                logger.info("agent tool call name=%s args=%s", fn_name, fn_args)
                handler = TOOL_HANDLERS.get(fn_name)
                if handler:
                    result = handler(**fn_args)
                else:
                    result = f"Unknown tool: {fn_name}"
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result,
                })
        logger.warning("agent exceeded max tool rounds=%d", _MAX_TOOL_ROUNDS)
        return {"latest_version": None, "confidence": "unknown", "evidence": ["Exceeded max tool call rounds."]}

    def _chat(self, prompt: str, max_tokens: int | None = None) -> str:
        url = chat_completions_url(self.config.base_url)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        response_data = self._post(url, messages, max_tokens=max_tokens)
        message = response_data["choices"][0]["message"]
        return message.get("content") or message.get("reasoning_content") or ""

    def _post(self, url: str, messages: list[dict[str, Any]], tools: list | None = None, max_tokens: int | None = None) -> dict[str, Any]:
        logger.debug("agent request url=%s model=%s messages=%d", url, self.config.model, len(messages))
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0.2,
        }
        if tools:
            payload["tools"] = tools
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
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
    # Strip code fences
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    # Try direct parse first
    if stripped.startswith("{"):
        return stripped
    # Find JSON object in text
    match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", stripped, re.DOTALL)
    if match:
        return match.group()
    return stripped


def _ensure_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if isinstance(value, str):
        return [value]
    return []
