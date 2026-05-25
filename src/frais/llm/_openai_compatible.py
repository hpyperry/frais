from __future__ import annotations

import json as _json
import logging
from typing import Any

import openai

from ..store.config_store import ProviderConfig
from ._base import LLMClient, LLMRequestError

logger = logging.getLogger(__name__)


class OpenAICompatibleClient(LLMClient):
    """Base client for OpenAI-compatible chat completions APIs.

    Uses the OpenAI Python SDK for typed request/response handling.
    Provider-specific behavior (e.g. thinking control) is injected via
    _apply_thinking() which returns extra_body fields.
    """

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self._client = openai.OpenAI(
            api_key=config.api_key,
            base_url=config.url,
            timeout=300.0,
        )

    def close(self) -> None:
        self._client.close()

    def chat(self, system: str, user: str, max_tokens: int | None = None,
             *, disable_thinking: bool = False) -> str:
        messages = self._build_messages(system, user)
        thinking_enabled = self._model_supports_thinking()
        if disable_thinking:
            thinking_enabled = False
        payload = self._build_payload(messages, max_tokens)
        if self._model_supports_thinking():
            extra = self._apply_thinking(thinking_enabled)
            if extra is not None:
                payload["extra_body"] = extra
        return self._create(payload)

    def _build_messages(self, system: str, user: str) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        return messages

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

    def _apply_thinking(self, thinking_enabled: bool) -> dict[str, Any] | None:
        """Hook for subclasses to return extra_body fields for thinking control.

        Default is no-op. Provider-specific subclasses override this to return
        a dict of extra body parameters (e.g. {"thinking": {"type": "disabled"}}).
        These are passed via the OpenAI SDK's extra_body parameter.
        """
        return None

    def _create(self, payload: dict[str, Any]) -> str:
        logger.debug(
            "llm request base_url=%s model=%s",
            self.config.url,
            self.config.model,
        )
        logger.debug(
            "llm request payload=%s",
            _json.dumps(payload, ensure_ascii=False)[:2000],
        )
        try:
            response = self._client.chat.completions.create(**payload)
        except openai.APIStatusError as exc:
            body = str(exc.body) if exc.body else ""
            raise LLMRequestError(
                f"LLM request failed with HTTP {exc.status_code}. "
                f"Response body: {body[:300] or '<empty>'}",
                status_code=exc.status_code,
                response_text=body[:300] if body else "",
            ) from exc
        except (openai.APIConnectionError, openai.APITimeoutError) as exc:
            raise LLMRequestError(
                f"LLM connection failed: {exc.message}",
            ) from exc

        text: str | None = response.choices[0].message.content
        if not text:
            message_dict = response.choices[0].message.model_dump() if response.choices else {}
            raise LLMRequestError(
                f"LLM returned empty content. "
                f"Message keys: {list(message_dict)}",
                status_code=200,
                response_text=_json.dumps(message_dict),
            )
        logger.debug("llm response content=%s", text[:2000] if text else "(empty)")
        if response.usage:
            logger.debug(
                "llm token usage prompt=%s completion=%s total=%s",
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
                response.usage.total_tokens,
            )
        return text
