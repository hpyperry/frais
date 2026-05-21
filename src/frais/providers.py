from __future__ import annotations

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
        if base.endswith("/v1"):
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
    Provider(
        id="openai",
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        models=[
            ModelInfo(id="gpt-4o", name="GPT-4o", thinking_default=False),
            ModelInfo(id="gpt-4o-mini", name="GPT-4o Mini", thinking_default=False),
        ],
        thinking_param=None,
    ),
    Provider(
        id="kimi",
        name="Moonshot / Kimi",
        base_url="https://api.moonshot.cn/v1",
        models=[
            ModelInfo(id="kimi-k2.6", name="Kimi K2.6", thinking_default=True),
            ModelInfo(id="kimi-k2.5", name="Kimi K2.5", thinking_default=True),
            ModelInfo(id="moonshot-v1-auto", name="Moonshot V1 Auto", thinking_default=False),
        ],
        thinking_param={"thinking": {"type": "disabled"}},
    ),
    Provider(
        id="grok",
        name="xAI Grok",
        base_url="https://api.x.ai/v1",
        models=[
            ModelInfo(id="grok-4.3", name="Grok 4.3", thinking_default=True),
        ],
        thinking_param={"reasoning_effort": "none"},
    ),
    Provider(
        id="mistral",
        name="Mistral AI",
        base_url="https://api.mistral.ai/v1",
        models=[
            ModelInfo(id="mistral-small-latest", name="Mistral Small", thinking_default=False),
            ModelInfo(id="mistral-large-latest", name="Mistral Large", thinking_default=False),
        ],
        thinking_param=None,
    ),
    Provider(
        id="qwen",
        name="Qwen (Alibaba)",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        models=[
            ModelInfo(id="qwen3.7-max", name="Qwen 3.7 Max", thinking_default=False),
            ModelInfo(id="qwen3.6-plus", name="Qwen 3.6 Plus", thinking_default=False),
            ModelInfo(id="qwen3.6-flash", name="Qwen 3.6 Flash", thinking_default=False),
        ],
        thinking_param={"enable_thinking": False},
    ),
    Provider(
        id="zhipu",
        name="Zhipu AI (GLM)",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        models=[
            ModelInfo(id="glm-4-flash", name="GLM-4 Flash", thinking_default=False),
            ModelInfo(id="glm-4-plus", name="GLM-4 Plus", thinking_default=False),
        ],
        thinking_param=None,
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
