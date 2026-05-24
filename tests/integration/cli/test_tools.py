from __future__ import annotations

import httpx

from frais.web_tools import (
    _extract_text,
    _format_github_api,
    _github_url_to_api,
    web_fetch,
    web_fetch_batch,
    web_search,
)

# --- web_search ---


class _FakeDDGS:
    def __init__(self, results):
        self._results = results

    def text(self, query, max_results=5):
        return self._results


def test_web_search_returns_formatted_results(monkeypatch) -> None:
    fake = _FakeDDGS([{"title": "T", "href": "https://x.com", "body": "snippet"}])
    monkeypatch.setattr("frais.web_tools.DDGS", lambda: fake)
    result = web_search("test query")
    assert result == [{"title": "T", "url": "https://x.com", "snippet": "snippet"}]


def test_web_search_returns_empty_on_failure(monkeypatch) -> None:
    def raise_error():
        raise RuntimeError("search down")
    monkeypatch.setattr("frais.web_tools.DDGS", raise_error)
    result = web_search("test query")
    assert result == []


# --- web_fetch ---


def test_web_fetch_returns_extracted_text(monkeypatch) -> None:
    resp = httpx.Response(200, text="<html><body><p>Hello World</p></body></html>", request=httpx.Request("GET", "https://example.com"))
    monkeypatch.setattr(httpx.Client, "get", lambda self, url, **kw: resp)
    result = web_fetch("https://example.com")
    assert "Hello World" in result


def test_web_fetch_github_url_conversion(monkeypatch) -> None:
    data = {"tag_name": "v1.0.0", "body": "Release notes", "published_at": "2024-01-01", "name": "v1.0.0"}
    resp = httpx.Response(200, json=data, request=httpx.Request("GET", "https://api.github.com/repos/user/repo/releases/latest"))
    monkeypatch.setattr(httpx.Client, "get", lambda self, url, **kw: resp)
    result = web_fetch("https://github.com/user/repo")
    assert "Tag: v1.0.0" in result


def test_web_fetch_truncates_long_content(monkeypatch) -> None:
    long_html = "<html><body>" + ("x" * 6000) + "</body></html>"
    resp = httpx.Response(200, text=long_html, request=httpx.Request("GET", "https://example.com"))
    monkeypatch.setattr(httpx.Client, "get", lambda self, url, **kw: resp)
    result = web_fetch("https://example.com")
    assert result.endswith("...<truncated>")


def test_web_fetch_returns_error_message_on_failure(monkeypatch) -> None:
    def raise_error(self, url, **kw):
        raise RuntimeError("timeout")
    monkeypatch.setattr(httpx.Client, "get", raise_error)
    result = web_fetch("https://example.com")
    assert result.startswith("Failed to fetch:")


# --- web_fetch_batch ---


def test_web_fetch_batch_aggregates_results(monkeypatch) -> None:
    monkeypatch.setattr("frais.web_tools.web_fetch", lambda url: f"content of {url}")
    result = web_fetch_batch(["https://a.com", "https://b.com"])
    assert result == {"https://a.com": "content of https://a.com", "https://b.com": "content of https://b.com"}


def test_web_fetch_batch_single() -> None:
    result = web_fetch_batch(["https://a.com"])
    assert len(result) == 1


# --- _github_url_to_api ---


def test_github_url_to_api_root() -> None:
    result = _github_url_to_api("https://github.com/user/repo/")
    assert result == "https://api.github.com/repos/user/repo/releases/latest"


def test_github_url_to_api_no_trailing_slash() -> None:
    result = _github_url_to_api("https://github.com/user/repo")
    assert result == "https://api.github.com/repos/user/repo/releases/latest"


def test_github_url_to_api_non_github_url() -> None:
    result = _github_url_to_api("https://example.com/download")
    assert result is None


# --- _format_github_api ---


def test_format_github_api_list() -> None:
    data = [{"tag_name": "v2.0.0", "body": "fixes", "published_at": "2024-06-01", "name": "v2.0.0"}]
    result = _format_github_api(data, "https://api.github.com/repos/user/repo/releases/latest")
    assert "Tag: v2.0.0" in result
    assert "fixes" in result


def test_format_github_api_empty_list() -> None:
    result = _format_github_api([], "")
    assert result == "No releases found."


def test_format_github_api_dict() -> None:
    data = {"tag_name": "v3.0", "body": "major release", "published_at": "2025-01-01"}
    result = _format_github_api(data, "")
    assert "Tag: v3.0" in result


def test_format_github_api_falls_back_to_name() -> None:
    data = {"name": "Release 1", "body": "", "published_at": ""}
    result = _format_github_api(data, "")
    assert "Tag: Release 1" in result


# --- _extract_text ---


def test_extract_text_removes_tags() -> None:
    result = _extract_text("<html><body><p>Hello</p></body></html>")
    assert result == "Hello"


def test_extract_text_removes_scripts() -> None:
    result = _extract_text('<script>alert("x")</script><p>text</p>')
    assert "alert" not in result
    assert "text" in result


def test_extract_text_collapses_whitespace() -> None:
    result = _extract_text("<p>a   b\n\nc</p>")
    assert result == "a b c"
