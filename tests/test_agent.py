from __future__ import annotations

from frais.providers import PROVIDERS, get_model_thinking_param, get_provider


def test_provider_chat_url_appends_v1_chat_completions() -> None:
    provider = get_provider("deepseek")
    assert provider is not None
    assert provider.chat_url == "https://api.deepseek.com/v1/chat/completions"


def test_provider_chat_url_accepts_existing_v1_path() -> None:
    provider = get_provider("openai")
    assert provider is not None
    assert provider.chat_url == "https://api.openai.com/v1/chat/completions"


def test_provider_chat_url_handles_trailing_slash() -> None:
    # Mistral base_url is "https://api.mistral.ai/v1" so it should end with /v1/chat/completions
    provider = get_provider("mistral")
    assert provider is not None
    assert provider.chat_url.startswith("https://api.mistral.ai/v1/chat/completions")


def test_get_model_thinking_param_returns_disabled_for_thinking_model() -> None:
    provider = get_provider("deepseek")
    assert provider is not None
    param = get_model_thinking_param(provider, "deepseek-v4-pro")
    assert param == {"thinking": {"type": "disabled"}}


def test_get_model_thinking_param_returns_none_for_non_thinking_model() -> None:
    provider = get_provider("openai")
    assert provider is not None
    param = get_model_thinking_param(provider, "gpt-4o")
    assert param is None


def test_get_model_thinking_param_returns_none_when_provider_has_no_param() -> None:
    provider = get_provider("mistral")
    assert provider is not None
    # mistral-large-latest has thinking_default=False, and provider has no thinking_param
    param = get_model_thinking_param(provider, "mistral-large-latest")
    assert param is None


def test_get_provider_returns_none_for_unknown() -> None:
    assert get_provider("nonexistent") is None


def test_all_providers_have_models() -> None:
    for p in PROVIDERS:
        assert len(p.models) > 0, f"{p.id} has no models"


def test_all_providers_have_chat_url() -> None:
    for p in PROVIDERS:
        url = p.chat_url
        assert url.endswith("/chat/completions"), f"{p.id} chat_url: {url}"
