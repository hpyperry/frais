from __future__ import annotations

from typing import Any

from ._anthropic import AnthropicClient
from ._openai_compatible import OpenAICompatibleClient


class DeepSeekOpenAIClient(OpenAICompatibleClient):
    """DeepSeek provider using OpenAI-compatible protocol."""

    def _apply_thinking(self, thinking_enabled: bool) -> dict[str, Any] | None:
        return {"thinking": {"type": "enabled" if thinking_enabled else "disabled"}}


class DeepSeekAnthropicClient(AnthropicClient):
    """DeepSeek provider using Anthropic-compatible protocol.

    Thinking control uses DeepSeek's own thinking format via extra_body
    rather than the Anthropic-native thinking parameter.
    """

    def _apply_thinking(self, thinking_enabled: bool) -> dict[str, Any] | None:
        return None

    def _build_extra_body(self, thinking_enabled: bool) -> dict[str, Any] | None:
        return {"thinking": {"type": "enabled" if thinking_enabled else "disabled"}}
