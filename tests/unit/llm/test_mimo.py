from __future__ import annotations

import pytest

from frais.llm import MiMoClient, OpenAICompatibleClient, get_client
from frais.providers import ModelInfo, Provider, get_provider
from frais.store.config_store import ProviderConfig


def _test_provider(**kw) -> Provider:
    defaults = {
        "id": "test",
        "name": "Test",
        "protocol_urls": {"openai": "https://api.test.com/v1"},
        "models": [ModelInfo(id="test-model", name="Test Model")],
        "protocols": ["openai"],
        "web_search_protocols": [],
    }
    return Provider(**(defaults | kw))


def _test_config(**kw) -> ProviderConfig:
    defaults = {
        "provider": _test_provider(),
        "model": "test-model",
        "api_key": "sk-test",
    }
    return ProviderConfig(**(defaults | kw))


def _config_with_thinking(model_supports: bool = True) -> ProviderConfig:
    provider = _test_provider(
        models=[ModelInfo(id="test-model", name="Test", supports_thinking=model_supports)],
    )
    return ProviderConfig(provider=provider, model="test-model", api_key="sk-test")


# --- factory tests ---


def test_get_client_returns_mimo_client() -> None:
    config = ProviderConfig(
        provider=get_provider("mimo"),
        model="mimo-v2.5-pro",
        api_key="sk-test",
    )
    client = get_client(config)
    assert isinstance(client, MiMoClient)
    client.close()


# --- client init tests ---


class TestMiMoClientInit:
    def test_raises_when_config_not_ready(self) -> None:
        config = _test_config(api_key="")
        with pytest.raises(ValueError, match="incomplete"):
            MiMoClient(config)

    def test_uses_url_from_config(self) -> None:
        config = _test_config(url="https://api.test.com/v1")
        client = MiMoClient(config)
        assert str(client._client.base_url) == "https://api.test.com/v1/"
        client.close()


# --- payload tests ---


class TestMiMoPayload:
    def test_uses_max_completion_tokens(self, monkeypatch) -> None:
        captured: dict = {}

        def fake_create(inst, payload):
            captured.update(payload)
            return "ok"

        monkeypatch.setattr(OpenAICompatibleClient, "_create", fake_create)
        config = _test_config()
        client = MiMoClient(config)
        client.chat("system", "user", max_tokens=100)
        client.close()
        assert "max_completion_tokens" in captured
        assert captured["max_completion_tokens"] == 100
        assert "max_tokens" not in captured

    def test_defaults_zero_max_tokens_not_set(self, monkeypatch) -> None:
        captured: dict = {}

        def fake_create(inst, payload):
            captured.update(payload)
            return "ok"

        monkeypatch.setattr(OpenAICompatibleClient, "_create", fake_create)
        config = _test_config()
        client = MiMoClient(config)
        client.chat("", "hello")  # max_tokens=None -> 0 in _build_messages, not set
        client.close()
        assert "max_completion_tokens" not in captured


class TestMiMoChat:
    def test_extracts_result_from_create(self, monkeypatch) -> None:
        monkeypatch.setattr(OpenAICompatibleClient, "_create", lambda s, p: "hello")
        config = _test_config()
        client = MiMoClient(config)
        result = client.chat("system", "user")
        assert result == "hello"
        client.close()


# --- thinking tests ---


class TestMiMoThinking:
    def test_thinking_enabled_by_default(self, monkeypatch) -> None:
        captured: dict = {}

        def fake_create(inst, payload):
            captured.update(payload)
            return "ok"

        monkeypatch.setattr(OpenAICompatibleClient, "_create", fake_create)
        config = _config_with_thinking()
        client = MiMoClient(config)
        client.chat("", "hello")
        client.close()
        assert captured.get("extra_body") == {"thinking": {"type": "enabled"}}

    def test_disable_thinking_injects_disabled(self, monkeypatch) -> None:
        captured: dict = {}

        def fake_create(inst, payload):
            captured.update(payload)
            return "ok"

        monkeypatch.setattr(OpenAICompatibleClient, "_create", fake_create)
        config = _config_with_thinking()
        client = MiMoClient(config)
        client.chat("", "hello", disable_thinking=True)
        client.close()
        assert captured.get("extra_body") == {"thinking": {"type": "disabled"}}

    def test_thinking_skipped_for_unsupported_model(self, monkeypatch) -> None:
        captured: dict = {}

        def fake_create(inst, payload):
            captured.update(payload)
            return "ok"

        monkeypatch.setattr(OpenAICompatibleClient, "_create", fake_create)
        config = _config_with_thinking(model_supports=False)
        client = MiMoClient(config)
        client.chat("", "hello")
        client.close()
        assert "extra_body" not in captured
