from __future__ import annotations

from ..config import ProviderConfig
from ._base import LLMClient, LLMRequestError
from ._openai_compatible import OpenAICompatibleClient
from ._deepseek import DeepSeekAnthropicClient, DeepSeekOpenAIClient
from ._anthropic import AnthropicClient

# Note: adding a provider to providers.PROVIDERS requires a corresponding
# entry here so get_client() can resolve it. The two registries must stay in sync.
_CLIENT_MAP: dict[tuple[str, str], type[LLMClient]] = {
    ("deepseek", "openai"): DeepSeekOpenAIClient,
    ("deepseek", "anthropic"): DeepSeekAnthropicClient,
}


def get_client(config: ProviderConfig, protocol: str = "openai") -> LLMClient:
    """Create the appropriate LLM client for a provider and protocol.

    Args:
        config: Provider configuration with API key, model, and thinking setting.
        protocol: API protocol to use (e.g. "openai", "anthropic"). Default "openai".

    Returns:
        An LLMClient instance for the (provider, protocol) pair.

    Raises:
        ValueError: If the provider does not support the requested protocol.
    """
    key = (config.provider.id, protocol)
    client_cls = _CLIENT_MAP.get(key)
    if client_cls is None:
        supported = [p for (prv, p) in _CLIENT_MAP if prv == config.provider.id]
        raise ValueError(
            f"Provider '{config.provider.id}' does not support protocol '{protocol}'. "
            f"Supported protocols for this provider: {supported or 'none'}"
        )
    return client_cls(config)


__all__ = [
    "AnthropicClient",
    "DeepSeekAnthropicClient",
    "DeepSeekOpenAIClient",
    "LLMClient",
    "LLMRequestError",
    "OpenAICompatibleClient",
    "get_client",
]
