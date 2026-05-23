from __future__ import annotations

import re
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
    base_url: str
    models: list[ModelInfo]

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
            ModelInfo(id="deepseek-v4-flash", name="DeepSeek V4 Flash", supports_thinking=True),
            ModelInfo(id="deepseek-v4-pro", name="DeepSeek V4 Pro", supports_thinking=True),
            ModelInfo(id="deepseek-chat", name="DeepSeek Chat (deprecated)", supports_thinking=False),
        ],
    ),
]


def get_provider(provider_id: str) -> Provider | None:
    for p in PROVIDERS:
        if p.id == provider_id:
            return p
    return None



