from __future__ import annotations

import httpx

from ..config import ProviderConfig
from ._base import LLMClient


class AnthropicClient(LLMClient):
    """Client for Anthropic-native Messages API. Not yet implemented."""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self._http = httpx.Client(
            headers={
                "x-api-key": config.api_key,
                "anthropic-version": "2023-06-01",
            },
            timeout=httpx.Timeout(15.0, read=300.0),
        )

    def close(self) -> None:
        self._http.close()

    def chat(self, system: str, user: str, max_tokens: int | None = None,
             *, disable_thinking: bool = False) -> str:
        raise NotImplementedError("AnthropicClient is not yet implemented")
