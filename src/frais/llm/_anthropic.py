from __future__ import annotations

import json as _json
import logging
from typing import Any

import anthropic

from ..store.config_store import ProviderConfig
from ._base import LLMClient, LLMRequestError

logger = logging.getLogger(__name__)


class AnthropicClient(LLMClient):
    """Client for Anthropic-native Messages API using the official SDK.

    Provider-specific behavior (e.g. thinking control) is injected via
    _apply_thinking() which returns the Anthropic-native thinking config,
    and _build_extra_body() for non-Anthropic extra body parameters.
    """

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self._client = anthropic.Anthropic(
            api_key=config.api_key,
            base_url=config.provider.base_url,
            timeout=300.0,
        )

    def close(self) -> None:
        self._client.close()

    def chat(self, system: str, user: str, max_tokens: int | None = None,
             *, disable_thinking: bool = False) -> str:
        thinking_enabled = self._resolve_thinking(disable_thinking)
        payload = self._build_payload(system, user, max_tokens)
        if self._model_supports_thinking():
            thinking_param = self._apply_thinking(thinking_enabled)
            if thinking_param is not None:
                payload["thinking"] = thinking_param
        extra = self._build_extra_body(thinking_enabled)
        if extra is not None:
            payload["extra_body"] = extra
        return self._create(payload)

    def _build_payload(self, system: str, user: str,
                       max_tokens: int | None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [{"role": "user", "content": user}],
            "temperature": 0.2,
            "max_tokens": max_tokens if max_tokens is not None else 4096,
        }
        if system:
            payload["system"] = system
        return payload

    def _apply_thinking(self, thinking_enabled: bool) -> dict[str, Any] | None:
        """Hook for subclasses to return Anthropic-native thinking config.

        Default returns enabled with budget or disabled. Provider-specific
        subclasses may override to return None and use _build_extra_body() instead.
        """
        if thinking_enabled:
            return {"type": "enabled", "budget_tokens": 4096}
        return {"type": "disabled"}

    def _build_extra_body(self, thinking_enabled: bool) -> dict[str, Any] | None:
        """Hook for subclasses to inject non-Anthropic extra body parameters.

        Default is no-op. Provider-specific subclasses override this to return
        provider-specific extra body fields (e.g. DeepSeek thinking format).
        """
        return None

    def _create(self, payload: dict[str, Any]) -> str:
        logger.debug(
            "llm request base_url=%s model=%s",
            self.config.provider.base_url,
            self.config.model,
        )
        logger.debug(
            "llm request payload=%s",
            _json.dumps(payload, ensure_ascii=False)[:2000],
        )
        try:
            response = self._client.messages.create(**payload)
        except anthropic.APIStatusError as exc:
            body = str(exc.body) if exc.body else ""
            raise LLMRequestError(
                f"LLM request failed with HTTP {exc.status_code}. "
                f"Response body: {body[:300] or '<empty>'}",
                status_code=exc.status_code,
                response_text=body[:300] if body else "",
            ) from exc
        except (anthropic.APIConnectionError, anthropic.APITimeoutError) as exc:
            raise LLMRequestError(
                f"LLM connection failed: {exc.message}",
            ) from exc

        text = "".join(
            block.text for block in response.content
            if hasattr(block, "text") and block.text
        )
        if not text:
            block_types = [getattr(b, "type", "unknown") for b in response.content]
            raise LLMRequestError(
                f"LLM returned empty content. "
                f"Content block types: {block_types}",
                status_code=200,
                response_text=_json.dumps(block_types),
            )
        logger.debug("llm response content=%s", text[:2000] if text else "(empty)")
        if response.usage:
            logger.debug(
                "llm token usage input=%s output=%s",
                response.usage.input_tokens,
                response.usage.output_tokens,
            )
        return text
