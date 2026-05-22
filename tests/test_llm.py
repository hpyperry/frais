from __future__ import annotations

import httpx
import pytest

from frais.llm import LLMClient, LLMRequestError
from frais.config import ProviderConfig
from frais.models import SoftwareItem, SourceKind, UpdateCandidate
from frais.providers import PROVIDERS, ModelInfo, Provider, get_model_thinking_param, get_provider


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
    defaults = {"provider": _test_provider(), "model": "test-model", "api_key": "sk-test"}
    return ProviderConfig(**(defaults | kw))


def _fake_response(json_data: dict) -> httpx.Response:
    return httpx.Response(200, json=json_data, request=httpx.Request("POST", "https://api.test.com"))


# --- provider tests ---


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


# --- LLMClient tests ---


class TestLLMClientInit:
    def test_raises_when_config_not_ready(self) -> None:
        config = _test_config(api_key="")
        with pytest.raises(ValueError, match="incomplete"):
            LLMClient(config)

    def test_succeeds_when_config_ready(self) -> None:
        client = LLMClient(_test_config())
        assert client.config.model == "test-model"


class TestSummarizeCandidate:
    def test_returns_summary_string(self, monkeypatch) -> None:
        monkeypatch.setattr(LLMClient, "chat", lambda *a, **kw: "建议立即更新")
        client = LLMClient(_test_config())
        item = SoftwareItem(id="com.example.app", name="MyApp", kind="application", source=SourceKind.APPLICATION, current_version="1.0")
        candidate = UpdateCandidate(item=item, latest_version="2.0")
        result = client.summarize_candidate(candidate)
        assert result == "建议立即更新"


class TestTestConnection:
    def test_returns_ok(self, monkeypatch) -> None:
        monkeypatch.setattr(LLMClient, "chat", lambda *a, **kw: "ok")
        client = LLMClient(_test_config())
        assert client.test_connection() == "ok"


class TestChat:
    def test_extracts_content_from_response(self, monkeypatch) -> None:
        def fake_post(inst, url, messages, max_tokens=None, disable_thinking=False):
            return {"choices": [{"message": {"content": "hello"}}]}
        monkeypatch.setattr(LLMClient, "_post", fake_post)
        client = LLMClient(_test_config())
        result = client.chat("system prompt", "user prompt")
        assert result == "hello"

    def test_falls_back_to_reasoning_content(self, monkeypatch) -> None:
        def fake_post(inst, url, messages, max_tokens=None, disable_thinking=False):
            return {"choices": [{"message": {"reasoning_content": "thinking..."}}]}
        monkeypatch.setattr(LLMClient, "_post", fake_post)
        client = LLMClient(_test_config())
        result = client.chat("", "user prompt")
        assert result == "thinking..."


class TestPost:
    def test_builds_payload_correctly(self, monkeypatch) -> None:
        captured = {}
        def fake_post(url, **kw):
            captured.update(kw)
            return _fake_response({"choices": [{"message": {"content": "ok"}}]})
        monkeypatch.setattr(httpx, "post", fake_post)
        client = LLMClient(_test_config())
        client._post("https://api.test.com/v1/chat/completions", [{"role": "user", "content": "hi"}])
        assert captured["json"]["model"] == "test-model"
        assert captured["json"]["messages"] == [{"role": "user", "content": "hi"}]
        assert captured["json"]["temperature"] == 0.2
        assert "Authorization" in captured["headers"]

    def test_raises_llm_request_error_on_http_failure(self, monkeypatch) -> None:
        bad_response = httpx.Response(500, json={"error": "server error"}, request=httpx.Request("POST", "https://api.test.com"))
        def return_bad_response(url, **kw):
            return bad_response
        monkeypatch.setattr(httpx, "post", return_bad_response)
        client = LLMClient(_test_config())
        with pytest.raises(LLMRequestError) as exc_info:
            client._post("https://api.test.com/v1/chat/completions", [{"role": "user", "content": "hi"}])
        assert exc_info.value.status_code == 500


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


