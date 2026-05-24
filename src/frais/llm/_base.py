from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from ..store.config_store import ProviderConfig


class LLMClient(ABC):
    """Abstract interface for LLM provider clients.

    Concrete implementations handle protocol-specific request construction
    while provider-specific behavior is injected via subclass hooks like
    _apply_thinking().
    """

    def __init__(self, config: ProviderConfig) -> None:
        if not config.is_ready:
            raise ValueError("LLM config is incomplete. Run `frais config manage`.")
        self.config = config

    @abstractmethod
    def chat(self, system: str, user: str, max_tokens: int | None = None,
             *, disable_thinking: bool = False) -> str:
        """Send a chat completion request and return the response text."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Close the underlying HTTP client and release connections."""
        ...

    def test_connection(self) -> str:
        """Send a minimal request to verify the provider is reachable."""
        try:
            return self.chat("", "Reply with exactly: ok", max_tokens=64)
        except NotImplementedError:
            raise NotImplementedError(
                f"{type(self).__name__} does not implement chat() — "
                f"test_connection() is not available for this client."
            )

    def _model_supports_thinking(self) -> bool:
        for m in self.config.provider.models:
            if m.id == self.config.model:
                return m.supports_thinking
        return False

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


class LLMRequestError(RuntimeError):
    """Error raised when an LLM API request fails."""

    def __init__(self, message: str, status_code: int | None = None,
                 response_text: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text

    @classmethod
    def from_response(cls, response: httpx.Response) -> LLMRequestError:
        body = response.text.strip()
        if len(body) > 300:
            body = body[:300] + "...<truncated>"
        url_str = str(response.url)
        if len(url_str) > 200:
            url_str = url_str[:200] + "..."
        return cls(
            (
                f"LLM request failed with HTTP {response.status_code} at {url_str}. "
                f"Response body: {body or '<empty>'}"
            ),
            status_code=response.status_code,
            response_text=body,
        )
