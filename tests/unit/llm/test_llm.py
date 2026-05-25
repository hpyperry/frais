from __future__ import annotations

import httpx
import openai
import pytest

from frais.commands.summarize import summarize_candidate
from frais.llm import (
    DeepSeekOpenAIClient,
    LLMClient,
    LLMRequestError,
    OpenAICompatibleClient,
    get_client,
)
from frais.models import SoftwareItem, SourceKind, UpdateCandidate
from frais.providers import PROVIDERS, ModelInfo, Provider, get_provider
from frais.store.config_store import ProviderConfig

# --- helpers ---


def _test_provider(**kw) -> Provider:
    defaults = {
        "id": "test",
        "name": "Test",
        "base_url": "https://api.test.com",
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


class _FakeMessage:
    def __init__(self, content: str | None) -> None:
        self.content = content

    def model_dump(self) -> dict:
        return {"content": self.content}


class _FakeChoice:
    def __init__(self, content: str | None) -> None:
        self.message = _FakeMessage(content)


class _FakeUsage:
    prompt_tokens = 10
    completion_tokens = 20
    total_tokens = 30


class _FakeResponse:
    def __init__(self, content: str | None, *, usage: _FakeUsage | None = None) -> None:
        self.choices = [_FakeChoice(content)]
        self.usage = usage


# --- provider tests ---


def test_provider_base_url() -> None:
    provider = get_provider("deepseek")
    assert provider is not None
    assert provider.base_url == "https://api.deepseek.com"


def test_get_provider_returns_none_for_unknown() -> None:
    assert get_provider("nonexistent") is None


def test_all_providers_have_models() -> None:
    for p in PROVIDERS:
        assert len(p.models) > 0, f"{p.id} has no models"


def test_all_providers_have_base_url() -> None:
    for p in PROVIDERS:
        assert p.base_url.startswith("https://"), f"{p.id} base_url: {p.base_url}"


def test_providers_protocols_match_client_map() -> None:
    from frais.llm import _CLIENT_MAP

    for p in PROVIDERS:
        for protocol in p.protocols:
            assert (p.id, protocol) in _CLIENT_MAP, (
                f"Provider '{p.id}' declares protocol '{protocol}' but "
                f"_CLIENT_MAP has no entry for ({p.id!r}, {protocol!r})"
            )
    for (provider_id, protocol) in _CLIENT_MAP:
        provider = get_provider(provider_id)
        assert provider is not None, f"_CLIENT_MAP has ({provider_id!r}, {protocol!r}) but no such provider"
        assert protocol in provider.protocols, (
            f"_CLIENT_MAP has ({provider_id!r}, {protocol!r}) but "
            f"Provider.protocols = {provider.protocols}"
        )


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


def test_get_client_raises_for_unsupported_protocol() -> None:
    config = ProviderConfig(
        provider=get_provider("deepseek"),
        model="deepseek-v4-flash",
        api_key="sk-test",
    )
    with pytest.raises(ValueError, match="does not support protocol"):
        get_client(config, protocol="grpc")


def test_get_client_returns_deepseek_anthropic_client() -> None:
    from frais.llm._deepseek import DeepSeekAnthropicClient

    config = ProviderConfig(
        provider=get_provider("deepseek"),
        model="deepseek-v4-flash",
        api_key="sk-test",
    )
    client = get_client(config, protocol="anthropic")
    assert isinstance(client, DeepSeekAnthropicClient)
    client.close()


def test_get_client_reads_protocol_from_config() -> None:
    from frais.llm._deepseek import DeepSeekAnthropicClient

    config = ProviderConfig(
        provider=get_provider("deepseek"),
        model="deepseek-v4-flash",
        api_key="sk-test",
        protocol="anthropic",
    )
    client = get_client(config)
    assert isinstance(client, DeepSeekAnthropicClient)
    client.close()


def test_get_client_base_url_override(monkeypatch) -> None:
    """Client uses custom base_url when provided."""
    monkeypatch.setattr("anthropic.Anthropic.__init__", lambda s, **kw: None)
    monkeypatch.setattr("anthropic.Anthropic.close", lambda s: None)
    from frais.llm._deepseek import DeepSeekAnthropicClient

    config = ProviderConfig(
        provider=get_provider("deepseek"),
        model="deepseek-v4-flash",
        api_key="sk-test",
        protocol="anthropic",
        base_url_override="https://my-proxy.example.com",
    )
    client = get_client(config)
    assert client._base_url == "https://my-proxy.example.com"
    client.close()


def test_supports_web_search() -> None:
    from frais.coordinator import supports_web_search

    config = ProviderConfig(
        provider=get_provider("deepseek"),
        model="deepseek-v4-flash",
        api_key="sk-test",
        protocol="openai",
    )
    assert not supports_web_search(config)

    config2 = ProviderConfig(
        provider=get_provider("deepseek"),
        model="deepseek-v4-flash",
        api_key="sk-test",
        protocol="anthropic",
    )
    assert supports_web_search(config2)


def test_supports_web_search_mimo() -> None:
    from frais.coordinator import supports_web_search

    config = ProviderConfig(
        provider=get_provider("mimo"),
        model="mimo-v2.5-pro",
        api_key="sk-test",
        protocol="openai",
    )
    assert supports_web_search(config)


def test_web_search_strategy_falls_back_to_ddgs(monkeypatch) -> None:
    from frais.web_tools import web_search_strategy
    from frais.store.config_store import ProviderConfig

    config = ProviderConfig(
        provider=get_provider("deepseek"),
        model="deepseek-v4-flash",
        api_key="sk-test",
        protocol="openai",
    )
    called = []

    def fake_search(q):
        called.append(q)
        return [{"title": "t", "url": "u", "snippet": "s"}]

    monkeypatch.setattr("frais.web_tools.web_search", fake_search)
    result = web_search_strategy(config, "test query")
    assert called == ["test query"]
    assert result == [{"title": "t", "url": "u", "snippet": "s"}]


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

    def test_uses_provider_base_url(self) -> None:
        config = _test_config()
        client = OpenAICompatibleClient(config)
        assert client._client.base_url == "https://api.test.com"
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
    def test_extracts_content_from_create(self, monkeypatch) -> None:
        monkeypatch.setattr(OpenAICompatibleClient, "_create", lambda s, p: "hello")
        config = _test_config()
        client = OpenAICompatibleClient(config)
        result = client.chat("system prompt", "user prompt")
        assert result == "hello"
        client.close()

    def test_excludes_system_message_when_empty(self, monkeypatch) -> None:
        captured: dict = {}

        def fake_create(inst, payload):
            captured.update(payload)
            return "ok"

        monkeypatch.setattr(OpenAICompatibleClient, "_create", fake_create)
        client = OpenAICompatibleClient(_test_config())
        client.chat("", "hello")
        client.close()
        messages = captured["messages"]
        assert len(messages) == 1
        assert messages[0] == {"role": "user", "content": "hello"}


class TestCreate:
    def test_passes_payload_to_sdk(self, monkeypatch) -> None:
        captured = {}

        def fake_create(**kwargs):
            captured.update(kwargs)
            return _FakeResponse("ok")

        client = OpenAICompatibleClient(_test_config())
        monkeypatch.setattr(client._client.chat.completions, "create", fake_create)
        client._create({"model": "test-model", "messages": [{"role": "user", "content": "hi"}], "temperature": 0.2})
        assert captured["model"] == "test-model"
        assert captured["messages"] == [{"role": "user", "content": "hi"}]
        assert captured["temperature"] == 0.2
        client.close()

    def test_raises_llm_request_error_on_api_status_error(self, monkeypatch) -> None:
        fake_response = httpx.Response(500, json={"error": "server error"},
                                        request=httpx.Request("POST", "https://api.test.com"))
        error = openai.APIStatusError("server error", response=fake_response, body={"error": "server error"})

        def fake_create(**kwargs):
            raise error

        client = OpenAICompatibleClient(_test_config())
        monkeypatch.setattr(client._client.chat.completions, "create", fake_create)
        with pytest.raises(LLMRequestError) as exc_info:
            client._create({"model": "m", "messages": [], "temperature": 0.2})
        assert exc_info.value.status_code == 500
        client.close()

    def test_raises_llm_request_error_on_connection_error(self, monkeypatch) -> None:
        def fake_create(**kwargs):
            raise openai.APIConnectionError(request=httpx.Request("POST", "https://api.test.com"))

        client = OpenAICompatibleClient(_test_config())
        monkeypatch.setattr(client._client.chat.completions, "create", fake_create)
        with pytest.raises(LLMRequestError, match="LLM connection failed"):
            client._create({"model": "m", "messages": [], "temperature": 0.2})
        client.close()

    def test_raises_llm_request_error_on_empty_content(self, monkeypatch) -> None:
        def fake_create(**kwargs):
            return _FakeResponse(None)

        client = OpenAICompatibleClient(_test_config())
        monkeypatch.setattr(client._client.chat.completions, "create", fake_create)
        with pytest.raises(LLMRequestError, match="empty content"):
            client._create({"model": "m", "messages": [], "temperature": 0.2})
        client.close()



# --- thinking tests ---


def _config_with_thinking(model_supports: bool = True) -> ProviderConfig:
    provider = _test_provider(
        models=[ModelInfo(id="test-model", name="Test", supports_thinking=model_supports)],
    )
    return ProviderConfig(provider=provider, model="test-model", api_key="sk-test")


def test_thinking_enabled_by_default(monkeypatch) -> None:
    captured: dict = {}

    def fake_create(inst, payload):
        captured.update(payload)
        return "ok"

    monkeypatch.setattr(OpenAICompatibleClient, "_create", fake_create)
    config = _config_with_thinking()
    client = DeepSeekOpenAIClient(config)
    client.chat("", "hello")
    client.close()
    assert captured.get("extra_body") == {"thinking": {"type": "enabled"}}


def test_disable_thinking_injects_disabled(monkeypatch) -> None:
    captured: dict = {}

    def fake_create(inst, payload):
        captured.update(payload)
        return "ok"

    monkeypatch.setattr(OpenAICompatibleClient, "_create", fake_create)
    config = _config_with_thinking()
    client = DeepSeekOpenAIClient(config)
    client.chat("", "hello", disable_thinking=True)
    client.close()
    assert captured.get("extra_body") == {"thinking": {"type": "disabled"}}


def test_thinking_skipped_for_unsupported_model(monkeypatch) -> None:
    captured: dict = {}

    def fake_create(inst, payload):
        captured.update(payload)
        return "ok"

    monkeypatch.setattr(OpenAICompatibleClient, "_create", fake_create)
    config = _config_with_thinking(model_supports=False)
    client = DeepSeekOpenAIClient(config)
    client.chat("", "hello")
    client.close()
    assert "extra_body" not in captured


# --- DeepSeekAnthropicClient tests ---


class TestDeepSeekAnthropicClientInit:
    def test_raises_when_config_not_ready(self) -> None:
        from frais.llm._deepseek import DeepSeekAnthropicClient

        config = _test_config(api_key="")
        with pytest.raises(ValueError, match="incomplete"):
            DeepSeekAnthropicClient(config)

    def test_uses_deepseek_anthropic_base_url(self, monkeypatch) -> None:
        from frais.llm._deepseek import DeepSeekAnthropicClient

        captured: dict = {}

        def fake_init(self, **kwargs):
            captured["kwargs"] = kwargs

        monkeypatch.setattr("anthropic.Anthropic.__init__", fake_init)
        monkeypatch.setattr("anthropic.Anthropic.close", lambda s: None)
        client = DeepSeekAnthropicClient(_test_config())
        client.close()
        assert captured["kwargs"].get("base_url") == "https://api.deepseek.com/anthropic"


class TestDeepSeekAnthropicChat:
    def test_extracts_result_from_create(self, monkeypatch) -> None:
        from frais.llm._deepseek import DeepSeekAnthropicClient

        monkeypatch.setattr(DeepSeekAnthropicClient, "_create", lambda s, **kw: "hello")
        config = _test_config()
        client = DeepSeekAnthropicClient(config)
        result = client.chat("system", "user")
        assert result == "hello"
        client.close()

    def test_system_as_top_level_param(self, monkeypatch) -> None:
        from frais.llm._deepseek import DeepSeekAnthropicClient

        captured: dict = {}

        def fake_create(self, **kwargs):
            captured.update(kwargs)
            return "ok"

        monkeypatch.setattr(DeepSeekAnthropicClient, "_create", fake_create)
        config = _test_config()
        client = DeepSeekAnthropicClient(config)
        client.chat("system prompt", "user message")
        client.close()
        assert captured.get("system") == "system prompt"
        assert captured["messages"] == [{"role": "user", "content": "user message"}]

    def test_excludes_system_when_empty(self, monkeypatch) -> None:
        from frais.llm._deepseek import DeepSeekAnthropicClient

        captured: dict = {}

        def fake_create(self, **kwargs):
            captured.update(kwargs)
            return "ok"

        monkeypatch.setattr(DeepSeekAnthropicClient, "_create", fake_create)
        config = _test_config()
        client = DeepSeekAnthropicClient(config)
        client.chat("", "hello")
        client.close()
        assert "system" not in captured
        assert len(captured["messages"]) == 1

    def test_defaults_max_tokens_to_4096(self, monkeypatch) -> None:
        from frais.llm._deepseek import DeepSeekAnthropicClient

        captured: dict = {}

        def fake_create(self, **kwargs):
            captured.update(kwargs)
            return "ok"

        monkeypatch.setattr(DeepSeekAnthropicClient, "_create", fake_create)
        config = _test_config()
        client = DeepSeekAnthropicClient(config)
        client.chat("", "hello")
        client.close()
        assert captured.get("max_tokens") == 4096

    def test_uses_explicit_max_tokens(self, monkeypatch) -> None:
        from frais.llm._deepseek import DeepSeekAnthropicClient

        captured: dict = {}

        def fake_create(self, **kwargs):
            captured.update(kwargs)
            return "ok"

        monkeypatch.setattr(DeepSeekAnthropicClient, "_create", fake_create)
        config = _test_config()
        client = DeepSeekAnthropicClient(config)
        client.chat("", "hello", max_tokens=100)
        client.close()
        assert captured.get("max_tokens") == 100


class TestDeepSeekAnthropicThinking:
    def test_thinking_enabled_by_default(self, monkeypatch) -> None:
        from frais.llm._deepseek import DeepSeekAnthropicClient

        captured: dict = {}

        def fake_create(self, **kwargs):
            captured.update(kwargs)
            return "ok"

        monkeypatch.setattr(DeepSeekAnthropicClient, "_create", fake_create)
        config = _config_with_thinking()
        client = DeepSeekAnthropicClient(config)
        client.chat("", "hello")
        client.close()
        assert captured.get("thinking") == {"type": "enabled", "budget_tokens": 1024}

    def test_disable_thinking_injects_disabled(self, monkeypatch) -> None:
        from frais.llm._deepseek import DeepSeekAnthropicClient

        captured: dict = {}

        def fake_create(self, **kwargs):
            captured.update(kwargs)
            return "ok"

        monkeypatch.setattr(DeepSeekAnthropicClient, "_create", fake_create)
        config = _config_with_thinking()
        client = DeepSeekAnthropicClient(config)
        client.chat("", "hello", disable_thinking=True)
        client.close()
        assert captured.get("thinking") == {"type": "disabled", "budget_tokens": 1024}

    def test_thinking_skipped_for_unsupported_model(self, monkeypatch) -> None:
        from frais.llm._deepseek import DeepSeekAnthropicClient

        captured: dict = {}

        def fake_create(self, **kwargs):
            captured.update(kwargs)
            return "ok"

        monkeypatch.setattr(DeepSeekAnthropicClient, "_create", fake_create)
        config = _config_with_thinking(model_supports=False)
        client = DeepSeekAnthropicClient(config)
        client.chat("", "hello")
        client.close()
        assert "thinking" not in captured


class TestDeepSeekAnthropicErrors:
    def test_raises_on_api_status_error(self, monkeypatch) -> None:
        from frais.llm._deepseek import DeepSeekAnthropicClient

        def fake_create(self, **kwargs):
            raise LLMRequestError("LLM request failed with HTTP 500.", status_code=500)

        monkeypatch.setattr(DeepSeekAnthropicClient, "_create", fake_create)
        config = _test_config()
        client = DeepSeekAnthropicClient(config)
        with pytest.raises(LLMRequestError) as exc_info:
            client.chat("", "hello")
        assert exc_info.value.status_code == 500
        client.close()

    def test_raises_on_connection_error(self, monkeypatch) -> None:
        from frais.llm._deepseek import DeepSeekAnthropicClient

        def fake_create(self, **kwargs):
            raise LLMRequestError("LLM connection failed: timeout")

        monkeypatch.setattr(DeepSeekAnthropicClient, "_create", fake_create)
        config = _test_config()
        client = DeepSeekAnthropicClient(config)
        with pytest.raises(LLMRequestError, match="LLM connection failed"):
            client.chat("", "hello")
        client.close()

    def test_raises_on_empty_content(self, monkeypatch) -> None:
        from frais.llm._deepseek import DeepSeekAnthropicClient

        def fake_create(self, **kwargs):
            raise LLMRequestError("LLM returned empty content.", status_code=200)

        monkeypatch.setattr(DeepSeekAnthropicClient, "_create", fake_create)
        config = _test_config()
        client = DeepSeekAnthropicClient(config)
        with pytest.raises(LLMRequestError, match="empty content"):
            client.chat("", "hello")
        client.close()


class TestDeepSeekAnthropicTestConnection:
    def test_returns_ok(self, monkeypatch) -> None:
        from frais.llm._deepseek import DeepSeekAnthropicClient

        monkeypatch.setattr(DeepSeekAnthropicClient, "_create", lambda s, **kw: "ok")
        config = _test_config()
        client = DeepSeekAnthropicClient(config)
        assert client.test_connection() == "ok"
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
