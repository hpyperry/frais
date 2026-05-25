from __future__ import annotations

from ..store.config_store import ProviderConfig
from ._base import LLMClient, LLMRequestError
from ._deepseek import DeepSeekAnthropicClient, DeepSeekOpenAIClient
from ._openai_compatible import OpenAICompatibleClient

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
        protocol: API protocol to use (e.g. "openai"). Default "openai".

    Returns:
        An LLMClient instance for the (provider, protocol) pair.

    Raises:
        ValueError: If the provider does not support the requested protocol.
    """
    if protocol not in config.provider.protocols:
        raise ValueError(
            f"Provider '{config.provider.id}' does not support protocol '{protocol}'. "
            f"Supported protocols: {config.provider.protocols}"
        )
    key = (config.provider.id, protocol)
    client_cls = _CLIENT_MAP.get(key)
    if client_cls is None:
        raise ValueError(
            f"No client implementation for ({config.provider.id!r}, {protocol!r}). "
            f"_CLIENT_MAP is missing this entry — add it to llm/__init__.py."
        )
    return client_cls(config)


__all__ = [
    "DeepSeekAnthropicClient",
    "DeepSeekOpenAIClient",
    "LLMClient",
    "LLMRequestError",
    "OpenAICompatibleClient",
    "get_client",
]
