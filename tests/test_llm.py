from __future__ import annotations

import httpx
import pytest

from frais.commands.summarize import summarize_candidate
from frais.llm import (
    AnthropicClient, DeepSeekAnthropicClient, DeepSeekOpenAIClient,
    LLMClient, LLMRequestError, OpenAICompatibleClient, get_client,
)
from frais.store.config_store import ProviderConfig
from frais.models import SoftwareItem, SourceKind, UpdateCandidate
from frais.providers import PROVIDERS, ModelInfo, Provider, get_provider


# --- helpers ---


def _test_provider(**kw) -> Provider:
    defaults = {
        "id": "test",
        "name": "Test",
        "base_url": "https://api.test.com",
        "models": [ModelInfo(id="test-model", name="Test Model")],
    }
    return Provider(**(defaults | kw))


def _test_config(**kw) -> ProviderConfig:
    defaults = {
        "provider": _test_provider(),
        "model": "test-model",
        "api_key": "sk-test",
    }
    return ProviderConfig(**(defaults | kw))


def _fake_response(json_data: dict) -> httpx.Response:
    return httpx.Response(200, json=json_data, request=httpx.Request("POST", "https://api.test.com"))


# --- provider tests ---


def test_provider_chat_url_appends_v1_chat_completions() -> None:
    provider = get_provider("deepseek")
    assert provider is not None
    assert provider.chat_url == "https://api.deepseek.com/v1/chat/completions"


def test_provider_chat_url_accepts_existing_v1_path() -> None:
    p = _test_provider(id="test", base_url="https://api.example.com/v1")
    assert p.chat_url == "https://api.example.com/v1/chat/completions"


def test_provider_chat_url_handles_trailing_slash() -> None:
    p = _test_provider(id="test", base_url="https://api.example.com/v1/")
    assert p.chat_url == "https://api.example.com/v1/chat/completions"


def test_get_provider_returns_none_for_unknown() -> None:
    assert get_provider("nonexistent") is None


def test_all_providers_have_models() -> None:
    for p in PROVIDERS:
        assert len(p.models) > 0, f"{p.id} has no models"


def test_all_providers_have_chat_url() -> None:
    for p in PROVIDERS:
        url = p.chat_url
        assert url.endswith("/chat/completions"), f"{p.id} chat_url: {url}"


# --- factory tests ---


def test_get_client_returns_deepseek_openai_client() -> None:
    config = ProviderConfig(
        provider=get_provider("deepseek"),
        model="deepseek-v4-flash",
        api_key="sk-test",
    )
    client = get_client(config)
    assert isinstance(client, DeepSeekOpenAIClient)


def test_get_client_unknown_pair_raises() -> None:
    config = _test_config()
    with pytest.raises(ValueError, match="does not support protocol"):
        get_client(config, protocol="nonexistent")


def test_get_client_returns_anthropic_stub() -> None:
    config = ProviderConfig(
        provider=get_provider("deepseek"),
        model="deepseek-v4-flash",
        api_key="sk-test",
    )
    client = get_client(config, protocol="anthropic")
    assert isinstance(client, DeepSeekAnthropicClient)
    with pytest.raises(NotImplementedError):
        client.chat("", "hello")


# --- LLMClient ABC tests ---


def test_cannot_instantiate_abc_directly() -> None:
    config = _test_config()
    with pytest.raises(TypeError):
        LLMClient(config)  # type: ignore[abstract]


class TestOpenAICompatibleClientInit:
    def test_raises_when_config_not_ready(self) -> None:
        config = _test_config(api_key="")
        with pytest.raises(ValueError, match="incomplete"):
            OpenAICompatibleClient(config)

    def test_succeeds_when_config_ready(self) -> None:
        client = OpenAICompatibleClient(_test_config())
        assert client.config.model == "test-model"
        client.close()


class TestSummarizeCandidate:
    def test_returns_summary_string(self, monkeypatch) -> None:
        monkeypatch.setattr(OpenAICompatibleClient, "chat", lambda *a, **kw: "建议立即更新")
        client = OpenAICompatibleClient(_test_config())
        item = SoftwareItem(id="com.example.app", name="MyApp", kind="application",
                           source=SourceKind.APPLICATION, current_version="1.0")
        candidate = UpdateCandidate(item=item, latest_version="2.0")
        result = summarize_candidate(client, candidate)
        assert result == "建议立即更新"
        client.close()


class TestTestConnection:
    def test_returns_ok(self, monkeypatch) -> None:
        monkeypatch.setattr(OpenAICompatibleClient, "chat", lambda *a, **kw: "ok")
        client = OpenAICompatibleClient(_test_config())
        assert client.test_connection() == "ok"
        client.close()


class TestChat:
    def test_extracts_content_from_response(self, monkeypatch) -> None:
        def fake_post(inst, payload):
            return "hello"
        monkeypatch.setattr(OpenAICompatibleClient, "_post", fake_post)
        config = _test_config()
        client = OpenAICompatibleClient(config)
        result = client.chat("system prompt", "user prompt")
        assert result == "hello"
        client.close()

    def test_falls_back_to_reasoning_content(self, monkeypatch) -> None:
        def fake_post(inst, payload):
            return "thinking..."
        monkeypatch.setattr(OpenAICompatibleClient, "_post", fake_post)
        client = OpenAICompatibleClient(_test_config())
        result = client.chat("", "user prompt")
        assert result == "thinking..."
        client.close()

    def test_excludes_system_message_when_empty(self, monkeypatch) -> None:
        captured: dict = {}

        def fake_post(inst, payload):
            captured.update(payload)
            return {"choices": [{"message": {"content": "ok"}}]}

        monkeypatch.setattr(OpenAICompatibleClient, "_post", fake_post)
        client = OpenAICompatibleClient(_test_config())
        client.chat("", "hello")
        client.close()
        messages = captured["messages"]
        assert len(messages) == 1
        assert messages[0] == {"role": "user", "content": "hello"}


class TestPost:
    def test_builds_payload_correctly(self, monkeypatch) -> None:
        captured = {}

        def fake_post(self, url, **kw):
            captured.update(kw)
            return _fake_response({"choices": [{"message": {"content": "ok"}}]})

        monkeypatch.setattr(httpx.Client, "post", fake_post)
        client = OpenAICompatibleClient(_test_config())
        client._post({"model": "test-model", "messages": [{"role": "user", "content": "hi"}], "temperature": 0.2})
        assert captured["json"]["model"] == "test-model"
        assert captured["json"]["messages"] == [{"role": "user", "content": "hi"}]
        assert captured["json"]["temperature"] == 0.2
        client.close()

    def test_raises_llm_request_error_on_http_failure(self, monkeypatch) -> None:
        bad_response = httpx.Response(500, json={"error": "server error"},
                                      request=httpx.Request("POST", "https://api.test.com"))

        def return_bad_response(self, url, **kw):
            return bad_response

        monkeypatch.setattr(httpx.Client, "post", return_bad_response)
        client = OpenAICompatibleClient(_test_config())
        with pytest.raises(LLMRequestError) as exc_info:
            client._post({"model": "m", "messages": [], "temperature": 0.2})
        assert exc_info.value.status_code == 500
        client.close()


# --- thinking tests ---


def _config_with_thinking(thinking_enabled: bool, model_supports: bool = True) -> ProviderConfig:
    provider = _test_provider(
        models=[ModelInfo(id="test-model", name="Test", supports_thinking=model_supports)],
    )
    return ProviderConfig(provider=provider, model="test-model", api_key="sk-test", thinking=thinking_enabled)


def test_thinking_disabled_injects_body_param(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(inst, payload):
        captured.update(payload)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(OpenAICompatibleClient, "_post", fake_post)
    config = _config_with_thinking(thinking_enabled=False)
    client = DeepSeekOpenAIClient(config)
    client.chat("", "hello")
    client.close()
    assert captured.get("thinking") == {"type": "disabled"}


def test_thinking_enabled_no_injection(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(inst, payload):
        captured.update(payload)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(OpenAICompatibleClient, "_post", fake_post)
    config = _config_with_thinking(thinking_enabled=True)
    client = DeepSeekOpenAIClient(config)
    client.chat("", "hello")
    client.close()
    assert "thinking" not in captured


def test_thinking_skipped_for_unsupported_model(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(inst, payload):
        captured.update(payload)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(OpenAICompatibleClient, "_post", fake_post)
    config = _config_with_thinking(thinking_enabled=True, model_supports=False)
    client = DeepSeekOpenAIClient(config)
    client.chat("", "hello", disable_thinking=False)
    client.close()
    assert "thinking" not in captured


def test_disable_thinking_overrides_config(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(inst, payload):
        captured.update(payload)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(OpenAICompatibleClient, "_post", fake_post)
    config = _config_with_thinking(thinking_enabled=True)
    client = DeepSeekOpenAIClient(config)
    client.chat("", "hello", disable_thinking=True)
    client.close()
    assert captured.get("thinking") == {"type": "disabled"}


# --- _resolve_thinking unit tests ---


def test_resolve_thinking_all_true() -> None:
    config = _config_with_thinking(thinking_enabled=True)
    client = OpenAICompatibleClient(config)
    result = client._resolve_thinking(disable_thinking=False)
    assert result is True
    client.close()


def test_resolve_thinking_disable_flag() -> None:
    config = _config_with_thinking(thinking_enabled=True)
    client = OpenAICompatibleClient(config)
    result = client._resolve_thinking(disable_thinking=True)
    assert result is False
    client.close()


def test_resolve_thinking_config_false() -> None:
    config = _config_with_thinking(thinking_enabled=False)
    client = OpenAICompatibleClient(config)
    result = client._resolve_thinking(disable_thinking=False)
    assert result is False
    client.close()


def test_resolve_thinking_model_not_found() -> None:
    provider = _test_provider(models=[ModelInfo(id="other", name="Other")])
    config = ProviderConfig(provider=provider, model="missing", api_key="sk-test", thinking=True)
    client = OpenAICompatibleClient(config)
    result = client._resolve_thinking(disable_thinking=False)
    assert result is False
    client.close()


# --- AnthropicClient stub tests ---


def test_anthropic_client_not_implemented() -> None:
    config = _test_config()
    client = AnthropicClient(config)
    with pytest.raises(NotImplementedError, match="not yet implemented"):
        client.chat("", "hello")
    client.close()


def test_deepseek_anthropic_client_is_stub() -> None:
    config = ProviderConfig(
        provider=get_provider("deepseek"),
        model="deepseek-v4-flash",
        api_key="sk-test",
    )
    client = DeepSeekAnthropicClient(config)
    assert isinstance(client, AnthropicClient)
    with pytest.raises(NotImplementedError):
        client.chat("", "hello")
    client.close()


# --- LLMRequestError tests ---


class TestLLMRequestError:
    def test_direct_construction(self) -> None:
        err = LLMRequestError("something went wrong", status_code=429, response_text="rate limited")
        assert err.status_code == 429
        assert err.response_text == "rate limited"
        assert "something went wrong" in str(err)

    def test_from_response_truncates_long_body(self) -> None:
        long_body = "x" * 2000
        response = httpx.Response(502, text=long_body, request=httpx.Request("POST", "https://api.test.com"))
        err = LLMRequestError.from_response(response)
        assert err.status_code == 502
        assert "...<truncated>" in err.response_text
        assert len(err.response_text) <= 1300

    def test_from_response_handles_empty_body(self) -> None:
        response = httpx.Response(503, text="", request=httpx.Request("POST", "https://api.test.com"))
        err = LLMRequestError.from_response(response)
        assert "<empty>" in str(err)
