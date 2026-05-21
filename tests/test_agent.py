from __future__ import annotations

from mise.agent import chat_completions_url


def test_chat_completions_url_accepts_base_url() -> None:
    assert chat_completions_url("https://api.deepseek.com") == "https://api.deepseek.com/chat/completions"


def test_chat_completions_url_accepts_v1_base_url() -> None:
    assert chat_completions_url("https://api.deepseek.com/v1") == "https://api.deepseek.com/v1/chat/completions"


def test_chat_completions_url_accepts_full_endpoint() -> None:
    assert (
        chat_completions_url("https://api.deepseek.com/v1/chat/completions")
        == "https://api.deepseek.com/v1/chat/completions"
    )
