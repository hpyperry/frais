from __future__ import annotations

from typing import Any

from ._anthropic import AnthropicClient
from ._openai_compatible import OpenAICompatibleClient


class DeepSeekOpenAIClient(OpenAICompatibleClient):
    """DeepSeek provider using OpenAI-compatible protocol."""

    def _apply_thinking(self, payload: dict[str, Any], thinking_enabled: bool) -> None:
        if not thinking_enabled:
            payload["thinking"] = {"type": "disabled"}


class DeepSeekAnthropicClient(AnthropicClient):
    """DeepSeek provider using Anthropic-compatible protocol. Reserved for web_search tool."""
    pass
