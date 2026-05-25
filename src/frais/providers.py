from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ModelInfo:
    id: str
    name: str
    supports_thinking: bool = False  # True if model supports extended thinking control


@dataclass(slots=True)
class Provider:
    id: str
    name: str
    models: list[ModelInfo]
    protocols: list[str]
    web_search_protocols: list[str]  # protocols that support server-side web search
    protocol_urls: dict[str, str]  # protocol → default endpoint URL


PROVIDERS: list[Provider] = [
    Provider(
        id="deepseek",
        name="DeepSeek",
        models=[
            ModelInfo(id="deepseek-v4-flash", name="DeepSeek V4 Flash", supports_thinking=True),
            ModelInfo(id="deepseek-v4-pro", name="DeepSeek V4 Pro", supports_thinking=True),
            ModelInfo(id="deepseek-chat", name="DeepSeek Chat (deprecated)", supports_thinking=False),
        ],
        protocols=["openai", "anthropic"],
        web_search_protocols=["anthropic"],
        protocol_urls={
            "openai": "https://api.deepseek.com",
            "anthropic": "https://api.deepseek.com/anthropic",
        },
    ),
    Provider(
        id="mimo",
        name="Xiaomi MiMo",
        models=[
            ModelInfo(id="mimo-v2.5-pro", name="MiMo V2.5 Pro", supports_thinking=True),
            ModelInfo(id="mimo-v2-flash", name="MiMo V2 Flash", supports_thinking=False),
        ],
        protocols=["openai"],
        web_search_protocols=["openai"],
        protocol_urls={
            "openai": "https://api.xiaomimimo.com/v1",
        },
    ),
]


def get_provider(provider_id: str) -> Provider | None:
    for p in PROVIDERS:
        if p.id == provider_id:
            return p
    return None


def get_protocol_url(provider: Provider, protocol: str) -> str:
    """Return the default endpoint URL for a (provider, protocol) pair."""
    return provider.protocol_urls.get(protocol, "")
