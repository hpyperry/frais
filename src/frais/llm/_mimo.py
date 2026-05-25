from __future__ import annotations

from typing import Any

from ._openai_compatible import OpenAICompatibleClient


class MiMoClient(OpenAICompatibleClient):
    """Xiaomi MiMo provider using OpenAI-compatible protocol.

    Differs from the base OpenAI-compatible client by sending
    ``max_completion_tokens`` instead of ``max_tokens`` in the
    request payload, per MiMo's API convention.
    """

    def _build_payload(self, messages: list[dict[str, str]],
                       max_tokens: int | None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0.2,
        }
        if max_tokens is not None:
            payload["max_completion_tokens"] = max_tokens
        return payload

    def _apply_thinking(self, thinking_enabled: bool) -> dict[str, Any] | None:
        return {"thinking": {"type": "enabled" if thinking_enabled else "disabled"}}
