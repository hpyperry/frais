from __future__ import annotations

from typing import Any

from ._openai_compatible import OpenAICompatibleClient


class DeepSeekOpenAIClient(OpenAICompatibleClient):
    """DeepSeek provider using OpenAI-compatible protocol."""

    def _apply_thinking(self, thinking_enabled: bool) -> dict[str, Any] | None:
        return {"thinking": {"type": "enabled" if thinking_enabled else "disabled"}}
