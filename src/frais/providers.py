from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ModelInfo:
    id: str
    name: str
    thinking_default: bool = False  # True if model enables thinking by default


@dataclass(slots=True)
class Provider:
    id: str
    name: str
    base_url: str
    models: list[ModelInfo]
    thinking_param: dict[str, Any] | None = None  # Non-thinking disable parameter

    @property
    def chat_url(self) -> str:
        base = self.base_url.rstrip("/")
        if re.search(r"/v\d+$", base):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"


PROVIDERS: list[Provider] = [
    Provider(
        id="deepseek",
        name="DeepSeek",
        base_url="https://api.deepseek.com",
        models=[
            ModelInfo(id="deepseek-v4-flash", name="DeepSeek V4 Flash", thinking_default=True),
            ModelInfo(id="deepseek-v4-pro", name="DeepSeek V4 Pro", thinking_default=True),
            ModelInfo(id="deepseek-chat", name="DeepSeek Chat (deprecated)", thinking_default=False),
        ],
        thinking_param={"thinking": {"type": "disabled"}},
    ),
]


def get_provider(provider_id: str) -> Provider | None:
    for p in PROVIDERS:
        if p.id == provider_id:
            return p
    return None


def get_model_thinking_param(provider: Provider, model_id: str) -> dict[str, Any] | None:
    """Return the thinking-disable param for a model, or None if not needed."""
    for m in provider.models:
        if m.id == model_id:
            if m.thinking_default and provider.thinking_param:
                return provider.thinking_param
            return None
    return provider.thinking_param  # Fallback for unknown model
