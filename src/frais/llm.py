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
    "Summarize the update recommendation for this software in concise Chinese. "
    "Mention risk, dependency impact, and whether the user should update now. "
    "Do not invent facts beyond the provided evidence."
)


class LLMClient:
    """OpenAI-compatible LLM client for structured version research."""

    def __init__(self, config: ProviderConfig) -> None:
        if not config.is_ready:
            raise ValueError("LLM config is incomplete. Run `frais config manage`.")
        self.config = config

    def summarize_candidate(self, candidate: UpdateCandidate) -> str:
        """Generate Chinese-language update summary."""
        prompt = (
            f"{_SUMMARIZE_PROMPT}\n\n"
            f"Candidate: {json.dumps(candidate.to_dict(), ensure_ascii=False)}"
        )
        return self.chat("", prompt)

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



