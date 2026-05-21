from __future__ import annotations

import httpx

from checkupgrade.agent import AgentClient, chat_completions_url
from checkupgrade.config import RawLLMConfig


_FAKE_CONFIG = RawLLMConfig(
    provider="test",
    base_url="https://api.example.com/v1",
    model="test-model",
    api_key="sk-test-key-1234",
    api_key_source="env",
    thinking=False,
)


def _fake_response(body: dict) -> httpx.Response:
    req = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    return httpx.Response(200, json=body, request=req)


def test_chat_completions_url_accepts_base_url() -> None:
    assert chat_completions_url("https://api.deepseek.com") == "https://api.deepseek.com/chat/completions"


def test_chat_completions_url_accepts_v1_base_url() -> None:
    assert chat_completions_url("https://api.deepseek.com/v1") == "https://api.deepseek.com/v1/chat/completions"


def test_chat_completions_url_accepts_full_endpoint() -> None:
    assert (
        chat_completions_url("https://api.deepseek.com/v1/chat/completions")
        == "https://api.deepseek.com/v1/chat/completions"
    )


# --- thinking mode payload tests ---


def test_post_includes_thinking_when_config_enabled(monkeypatch) -> None:
    config = RawLLMConfig(
        provider="test", base_url="https://api.example.com/v1",
        model="test-model", api_key="sk-test", thinking=True,
    )
    client = AgentClient(config)
    payloads = []

    def fake_post(url, **kwargs):
        payloads.append(kwargs.get("json", {}))
        return _fake_response({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr("checkupgrade.agent.httpx.post", fake_post)
    client._chat("", "test")
    assert payloads[0].get("thinking") == {"type": "enabled"}


def test_post_includes_disabled_thinking_when_config_disabled(monkeypatch) -> None:
    client = AgentClient(_FAKE_CONFIG)
    payloads = []

    def fake_post(url, **kwargs):
        payloads.append(kwargs.get("json", {}))
        return _fake_response({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr("checkupgrade.agent.httpx.post", fake_post)
    client._chat("", "test")
    assert payloads[0].get("thinking") == {"type": "disabled"}


def test_enable_thinking_false_overrides_config(monkeypatch) -> None:
    config = RawLLMConfig(
        provider="test", base_url="https://api.example.com/v1",
        model="test-model", api_key="sk-test", thinking=True,
    )
    client = AgentClient(config)
    payloads = []

    def fake_post(url, **kwargs):
        payloads.append(kwargs.get("json", {}))
        return _fake_response({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr("checkupgrade.agent.httpx.post", fake_post)
    client._chat("", "test", enable_thinking=False)
    assert payloads[0].get("thinking") == {"type": "disabled"}


# --- reasoning_content fallback tests ---


def test_chat_uses_content_when_present(monkeypatch) -> None:
    client = AgentClient(_FAKE_CONFIG)

    def fake_post(url, **kwargs):
        return _fake_response({
            "choices": [{"message": {"content": "hello", "reasoning_content": "..."}}]
        })

    monkeypatch.setattr("checkupgrade.agent.httpx.post", fake_post)
    result = client._chat("", "test")
    assert result == "hello"


def test_chat_falls_back_to_reasoning_content(monkeypatch) -> None:
    client = AgentClient(_FAKE_CONFIG)

    def fake_post(url, **kwargs):
        return _fake_response({
            "choices": [{"message": {"reasoning_content": "answer from reasoning"}}]
        })

    monkeypatch.setattr("checkupgrade.agent.httpx.post", fake_post)
    result = client._chat("", "test")
    assert result == "answer from reasoning"


def test_chat_returns_empty_when_both_missing(monkeypatch) -> None:
    client = AgentClient(_FAKE_CONFIG)

    def fake_post(url, **kwargs):
        return _fake_response({
            "choices": [{"message": {}}]
        })

    monkeypatch.setattr("checkupgrade.agent.httpx.post", fake_post)
    result = client._chat("", "test")
    assert result == ""
