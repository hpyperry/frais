from __future__ import annotations

import json as _json
import logging
from typing import Any

import httpx

from ..store.config_store import ProviderConfig
from ._base import LLMClient, LLMRequestError

logger = logging.getLogger(__name__)


class OpenAICompatibleClient(LLMClient):
    """Base client for OpenAI-compatible chat completions APIs.

    Handles Bearer auth, /v1/chat/completions endpoint, and
    choices[0].message.content response parsing. Subclasses override
    _apply_thinking() to inject provider-specific thinking parameters.
    """

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self._http = httpx.Client(
            headers={"Authorization": f"Bearer {config.api_key}"},
            timeout=httpx.Timeout(15.0, read=300.0),
        )

    def close(self) -> None:
        self._http.close()

    def chat(self, system: str, user: str, max_tokens: int | None = None,
             *, disable_thinking: bool = False) -> str:
        messages = self._build_messages(system, user)
        thinking_enabled = self._resolve_thinking(disable_thinking)
        payload = self._build_payload(messages, max_tokens)
        if self._model_supports_thinking():
            self._apply_thinking(payload, thinking_enabled)
        return self._post(payload)

    def _model_supports_thinking(self) -> bool:
        for m in self.config.provider.models:
            if m.id == self.config.model:
                return m.supports_thinking
        return False

    def _build_messages(self, system: str, user: str) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        return messages

    def _resolve_thinking(self, disable_thinking: bool) -> bool:
        """Determine the effective thinking state.

        Thinking is enabled only when: user config says yes, caller hasn't
        overridden with disable_thinking, and the selected model supports it.
        """
        if disable_thinking:
            return False
        if not self.config.thinking:
            return False
        return self._model_supports_thinking()

    def _build_payload(self, messages: list[dict[str, str]],
                       max_tokens: int | None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0.2,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        return payload

    def _apply_thinking(self, payload: dict[str, Any], thinking_enabled: bool) -> None:
        """Hook for subclasses to inject thinking parameters into the payload.

        Default is no-op. Provider-specific subclasses override this to add
        thinking control fields (e.g. DeepSeek's {"thinking": {"type": "disabled"}}).
        """
        return

    def _post(self, payload: dict[str, Any]) -> str:
        url = self.config.provider.chat_url
        logger.debug("llm request url=%s model=%s", url, self.config.model)
        response = self._http.post(url, json=payload)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LLMRequestError.from_response(exc.response) from exc
        try:
            body: dict[str, Any] = response.json()
        except (_json.JSONDecodeError, ValueError) as exc:
            raise LLMRequestError(
                f"LLM returned non-JSON response at {url}. "
                f"Body preview: {response.text[:200]!r}",
                status_code=response.status_code,
                response_text=response.text,
            ) from exc
        message: dict[str, Any] = body["choices"][0]["message"]
        text = message.get("content") or message.get("reasoning_content") or ""
        if not text:
            raise LLMRequestError(
                f"LLM returned empty content at {url}. "
                f"Message keys: {list(message)}",
                status_code=response.status_code,
                response_text=_json.dumps(message),
            )
        return text
