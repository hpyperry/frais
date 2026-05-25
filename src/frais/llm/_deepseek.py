from __future__ import annotations

import logging
from typing import Any

import anthropic

from ..store.config_store import ProviderConfig
from ._base import LLMClient, LLMRequestError
from ._openai_compatible import OpenAICompatibleClient

logger = logging.getLogger(__name__)

DEEPSEEK_ANTHROPIC_BASE_URL = "https://api.deepseek.com/anthropic"


class DeepSeekAnthropicClient(LLMClient):
    """DeepSeek provider using Anthropic Messages protocol."""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        base_url = config.base_url_override or DEEPSEEK_ANTHROPIC_BASE_URL
        self._client = anthropic.Anthropic(
            api_key=config.api_key,
            base_url=base_url,
            timeout=300.0,
        )
        self._base_url = base_url

    def close(self) -> None:
        self._client.close()

    def chat(self, system: str, user: str, max_tokens: int | None = None,
             *, disable_thinking: bool = False) -> str:
        thinking_enabled = self._model_supports_thinking()
        if disable_thinking:
            thinking_enabled = False

        messages: list[dict[str, str]] = [{"role": "user", "content": user}]

        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": max_tokens or 4096,
            "temperature": 0.2,
        }

        if system:
            kwargs["system"] = system

        if self._model_supports_thinking():
            kwargs["thinking"] = {
                "type": "enabled" if thinking_enabled else "disabled",
                "budget_tokens": 1024,
            }

        return self._create(**kwargs)

    def _create(self, **kwargs: Any) -> str:
        logger.debug(
            "llm request base_url=%s model=%s",
            self._base_url,
            self.config.model,
        )
        try:
            response = self._client.messages.create(**kwargs)
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
                f"LLM connection failed: {exc}",
            ) from exc

        text_parts: list[str] = []
        for block in response.content:
            if getattr(block, "type", None) == "text":
                text_parts.append(getattr(block, "text", ""))
        text = "".join(text_parts)

        if not text:
            raise LLMRequestError(
                "LLM returned empty content.",
                status_code=200,
            )

        logger.debug("llm response content=%s", text[:2000] if text else "(empty)")
        if response.usage:
            logger.debug(
                "llm token usage input=%s output=%s",
                response.usage.input_tokens,
                response.usage.output_tokens,
            )

        return text

    def web_search(self, query: str) -> list[dict[str, str]]:
        """Execute a web search via the Anthropic protocol's web_search_20250305 tool."""
        tool_schema = {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 4,
        }
        try:
            response = self._client.messages.create(
                model=self.config.model,
                max_tokens=4096,
                system="You are a web search assistant. Use the web_search tool to find relevant results.",
                messages=[{"role": "user", "content": f"Search the web for: {query}"}],
                tools=[tool_schema],  # type: ignore[list-item]
            )
        except Exception as exc:
            logger.warning("anthropic web_search failed for %s: %s", query[:80], exc)
            return []

        results: list[dict[str, str]] = []
        for block in response.content:
            if getattr(block, "type", None) == "web_search_tool_result":
                content = getattr(block, "content", [])
                if isinstance(content, list):
                    for item in content:
                        results.append({
                            "title": getattr(item, "title", "") or "",
                            "url": getattr(item, "url", "") or "",
                            "snippet": "",
                        })
        return results


class DeepSeekOpenAIClient(OpenAICompatibleClient):
    """DeepSeek provider using OpenAI-compatible protocol."""

    def _apply_thinking(self, thinking_enabled: bool) -> dict[str, Any] | None:
        return {"thinking": {"type": "enabled" if thinking_enabled else "disabled"}}
