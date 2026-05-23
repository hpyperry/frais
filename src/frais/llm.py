from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from .config import ProviderConfig
from .models import UpdateCandidate
from .providers import get_model_thinking_param

logger = logging.getLogger(__name__)

_SUMMARIZE_PROMPT = (
    "You are helping a macOS user decide whether to update installed software. "
    "Write a concise update recommendation in Chinese.\n"
    "\n"
    "Rules:\n"
    "- Output 3-4 short bullet lines (each starting with \"- \"), no preamble or closing.\n"
    "- Use **bold** for version numbers, risk levels, and key actions.\n"
    "- Mention: what changed, risk level, dependency impact (if any), and a clear recommendation.\n"
    "- If the evidence includes URLs, reference the most credible one.\n"
    "- Never invent version numbers, CVEs, or changelog details not present in the data.\n"
    "- If evidence is weak or missing, say so honestly — prefer \"信息不足\" over guessing."
)


class LLMClient:
    """OpenAI-compatible LLM client for structured version research."""

    def __init__(self, config: ProviderConfig) -> None:
        if not config.is_ready:
            raise ValueError("LLM config is incomplete. Run `frais config manage`.")
        self.config = config
        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {config.api_key}"},
            timeout=httpx.Timeout(15.0, read=300.0),
        )

    def close(self) -> None:
        """Close the underlying HTTP client and its connection pool."""
        self._client.close()

    def summarize_candidate(self, candidate: UpdateCandidate) -> str:
        """Generate Chinese-language update summary."""
        d = candidate.to_dict()
        item = d.get("item", {})
        dep = d.get("dependency_impact", {})
        prompt = (
            f"{_SUMMARIZE_PROMPT}\n\n"
            f"Name: {item.get('name', 'unknown')}\n"
            f"Type: {item.get('kind', 'unknown')} ({item.get('source', 'unknown')})\n"
            f"Current version: {item.get('current_version', 'unknown')}\n"
            f"Latest version: {d.get('latest_version', 'unknown')}\n"
            f"Risk level: {d.get('risk_level', 'unknown')}\n"
            f"Auto-update available: {d.get('can_auto_update', False)}\n"
            f"Update command: {' '.join(d.get('command', [])) or '(manual)'}\n"
            f"Dependencies: {len(dep.get('depends_on', []))} packages\n"
            f"Used by: {len(dep.get('used_by', []))} packages\n"
            f"Evidence: {json.dumps(d.get('evidence', []), ensure_ascii=False)}\n"
            f"Release notes: {d.get('release_notes') or '(none)'}"
        )
        return self.chat("", prompt, max_tokens=500)

    def test_connection(self) -> str:
        return self.chat("", "Reply with exactly: ok", max_tokens=64)

    def chat(self, system: str, user: str, max_tokens: int | None = None,
             disable_thinking: bool = False) -> str:
        url = self.config.provider.chat_url
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        response_data = self._post(url, messages, max_tokens=max_tokens,
                                   disable_thinking=disable_thinking)
        message = response_data["choices"][0]["message"]
        return message.get("content") or message.get("reasoning_content") or ""

    def _post(self, url: str, messages: list[dict[str, Any]], max_tokens: int | None = None,
              disable_thinking: bool = False) -> dict[str, Any]:
        logger.debug("llm request url=%s model=%s messages=%d", url, self.config.model, len(messages))
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0.2,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if disable_thinking:
            thinking_param = get_model_thinking_param(self.config.provider, self.config.model)
            if thinking_param:
                payload.update(thinking_param)
        response = self._client.post(url, json=payload)
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
        if len(body) > 300:
            body = body[:300] + "...<truncated>"
        url_str = str(response.url)
        if len(url_str) > 200:
            url_str = url_str[:200] + "..."
        return cls(
            (
                f"LLM request failed with HTTP {response.status_code} at {url_str}. "
                f"Response body: {body or '<empty>'}"
            ),
            status_code=response.status_code,
            response_text=body,
        )



