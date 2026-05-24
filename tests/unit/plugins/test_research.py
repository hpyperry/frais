from __future__ import annotations

import json

from frais.llm import OpenAICompatibleClient
from frais.models import ResearchResult, SoftwareItem, SourceKind
from frais.plugins.applications import research as research
from frais.plugins.applications.research import (
    _digits_only,
    _ensure_list,
    _extract_json,
    _is_newer,
    _normalize,
    _parse_json_list,
    _parse_json_object,
    extract_version,
    generate_search_queries,
    pick_urls,
    research_application_update,
)


def _raise(exc):
    raise exc


def _dummy_llm(chat_return: str = '["q"]'):
    """Create an LLM client with the test provider."""
    from frais.providers import ModelInfo, Provider
    from frais.store.config_store import ProviderConfig

    p = Provider(id="test", name="Test", base_url="https://api.test.com",
                 models=[ModelInfo(id="test-model", name="Test Model")])
    config = ProviderConfig(provider=p, model="test-model", api_key="sk-test")
    return OpenAICompatibleClient(config)


# --- standalone research function tests ---


def test_generate_search_queries_parses_json_array(monkeypatch) -> None:
    client = _dummy_llm()
    monkeypatch.setattr(client, "chat", lambda *a, **kw: '["query one", "query two"]')
    item = SoftwareItem(id="com.example.app", name="MyApp", kind="application", source=SourceKind.APPLICATION, current_version="1.0")
    result = generate_search_queries(client, item)
    assert result == ["query one", "query two"]


def test_generate_search_queries_extracts_from_markdown(monkeypatch) -> None:
    client = _dummy_llm()
    monkeypatch.setattr(client, "chat", lambda *a, **kw: '```json\n["q1", "q2"]\n```')
    item = SoftwareItem(id="com.example.app", name="MyApp", kind="application", source=SourceKind.APPLICATION, current_version="1.0")
    result = generate_search_queries(client, item)
    assert result == ["q1", "q2"]


def test_generate_search_queries_empty_on_parse_failure(monkeypatch) -> None:
    client = _dummy_llm()
    monkeypatch.setattr(client, "chat", lambda *a, **kw: "not json at all")
    item = SoftwareItem(id="com.example.app", name="MyApp", kind="application", source=SourceKind.APPLICATION, current_version="1.0")
    result = generate_search_queries(client, item)
    assert result == []


def test_generate_search_queries_passes_disable_thinking(monkeypatch) -> None:
    client = _dummy_llm()
    calls = []
    def capture(system, user, max_tokens=None, disable_thinking=False):
        calls.append(disable_thinking)
        return '["q"]'
    monkeypatch.setattr(client, "chat", capture)
    item = SoftwareItem(id="com.example.app", name="MyApp", kind="application", source=SourceKind.APPLICATION, current_version="1.0")
    generate_search_queries(client, item)
    assert calls == [True]


def test_pick_urls_limits_to_three(monkeypatch) -> None:
    client = _dummy_llm()
    monkeypatch.setattr(client, "chat", lambda *a, **kw: '["u1","u2","u3","u4"]')
    item = SoftwareItem(id="com.example.app", name="MyApp", kind="application", source=SourceKind.APPLICATION, current_version="1.0")
    result = pick_urls(client, item, [{"title": "t", "url": "u", "snippet": "s"}])
    assert result == ["u1", "u2", "u3"]


def test_pick_urls_passes_disable_thinking(monkeypatch) -> None:
    client = _dummy_llm()
    calls = []
    monkeypatch.setattr(client, "chat", lambda *a, **kw: calls.append(kw.get("disable_thinking")) or '["u"]')
    item = SoftwareItem(id="com.example.app", name="MyApp", kind="application", source=SourceKind.APPLICATION, current_version="1.0")
    pick_urls(client, item, [])
    assert calls == [True]


def test_extract_version_returns_research_result(monkeypatch) -> None:
    client = _dummy_llm()
    response = json.dumps({"latest_version": "2.0", "confidence": "high", "evidence": ["changelog"], "release_notes": "Bug fixes"})
    monkeypatch.setattr(client, "chat", lambda *a, **kw: response)
    item = SoftwareItem(id="com.example.app", name="MyApp", kind="application", source=SourceKind.APPLICATION, current_version="1.0")
    result = extract_version(client, item, {"https://example.com": "content"})
    assert result.latest_version == "2.0"
    assert result.confidence == "high"
    assert result.evidence == ["changelog"]
    assert result.release_notes == "Bug fixes"


def test_extract_version_passes_disable_thinking(monkeypatch) -> None:
    client = _dummy_llm()
    calls = []
    monkeypatch.setattr(client, "chat", lambda *a, **kw: calls.append(kw.get("disable_thinking")) or "{}")
    item = SoftwareItem(id="com.example.app", name="MyApp", kind="application", source=SourceKind.APPLICATION, current_version="1.0")
    extract_version(client, item, {})
    assert calls == [True]


# --- research_application_update tests ---


def test_local_build_can_be_update_candidate(monkeypatch) -> None:
    monkeypatch.setattr(research.pipeline, "generate_search_queries", lambda llm, item: ["Tool macOS latest version"])
    monkeypatch.setattr(research.pipeline, "pick_urls", lambda llm, item, results: ["https://github.com/example/tool/releases"])
    monkeypatch.setattr(research.pipeline, "extract_version", lambda llm, item, content: ResearchResult(
        latest_version="0.4.0", confidence="high",
        evidence=["https://github.com/example/tool/releases/tag/v0.4.0"],
        release_notes="fixes",
    ))
    monkeypatch.setattr(research.pipeline, "web_search", lambda q: [{"title": "Tool", "url": "https://github.com/example/tool/releases", "snippet": ""}])
    monkeypatch.setattr(research.pipeline, "web_fetch_batch", lambda urls: dict.fromkeys(urls, "Tag: v0.4.0"))

    item = SoftwareItem(id="com.example.tool", name="Tool", kind="application", source=SourceKind.LOCAL_BUILD, current_version="0.3.0")
    candidate = research_application_update(_dummy_llm(), item)

    assert candidate is not None
    assert candidate.latest_version == "0.4.0"
    assert candidate.recommended_action is None
    assert not candidate.can_auto_update


def test_is_newer_detects_upgrade() -> None:
    assert _is_newer("1.0", "2.0")


def test_is_newer_rejects_same_version() -> None:
    assert not _is_newer("1.0", "1.0")


def test_is_newer_rejects_downgrade() -> None:
    assert not _is_newer("10.0.0", "2.0.0")


def test_is_newer_handles_missing_versions() -> None:
    assert not _is_newer(None, "1.0")
    assert not _is_newer("1.0", None)


# --- research_application_update iTunes fast path ---


def test_research_app_store_returns_candidate_when_newer(monkeypatch) -> None:
    monkeypatch.setattr(research.pipeline, "check_app_store_version", lambda item: ("2.0", 12345))
    item = SoftwareItem(id="com.example.app", name="App", kind="application", source=SourceKind.APP_STORE, current_version="1.0")
    result = research_application_update(_dummy_llm(), item)
    assert result is not None
    assert result.latest_version == "2.0"
    assert result.command == ["open", "macappstore://apps.apple.com/app/id12345"]


def test_research_app_store_returns_none_when_up_to_date(monkeypatch) -> None:
    monkeypatch.setattr(research.pipeline, "check_app_store_version", lambda item: ("1.0", None))
    item = SoftwareItem(id="com.example.app", name="App", kind="application", source=SourceKind.APP_STORE, current_version="1.0")
    result = research_application_update(_dummy_llm(), item)
    assert result is None


def test_research_app_store_falls_through_when_no_itunes_result(monkeypatch) -> None:
    monkeypatch.setattr(research.pipeline, "check_app_store_version", lambda item: (None, None))
    monkeypatch.setattr(research.pipeline, "generate_search_queries", lambda llm, item: ["q"])
    monkeypatch.setattr(research.pipeline, "pick_urls", lambda llm, item, results: ["https://example.com"])
    monkeypatch.setattr(research.pipeline, "extract_version", lambda llm, item, content: ResearchResult(latest_version="0.4.0", confidence="high"))
    monkeypatch.setattr(research.pipeline, "web_search", lambda q: [{"title": "T", "url": "https://example.com", "snippet": ""}])
    monkeypatch.setattr(research.pipeline, "web_fetch_batch", lambda urls: dict.fromkeys(urls, "v0.4.0"))
    item = SoftwareItem(id="com.example.app", name="App", kind="application", source=SourceKind.APP_STORE, current_version="0.3.0")
    result = research_application_update(_dummy_llm(), item)
    assert result is not None
    assert result.latest_version == "0.4.0"


# --- _llm_structured_research failure paths ---


def test_structured_research_returns_none_when_generate_queries_fails(monkeypatch) -> None:
    monkeypatch.setattr(research.pipeline, "generate_search_queries", lambda llm, item: _raise(RuntimeError("network error")))
    item = SoftwareItem(id="com.example.app", name="App", kind="application", source=SourceKind.APPLICATION, current_version="1.0")
    result = research_application_update(_dummy_llm(), item)
    assert result is None


def test_structured_research_returns_none_when_no_queries(monkeypatch) -> None:
    monkeypatch.setattr(research.pipeline, "generate_search_queries", lambda llm, item: [])
    item = SoftwareItem(id="com.example.app", name="App", kind="application", source=SourceKind.APPLICATION, current_version="1.0")
    result = research_application_update(_dummy_llm(), item)
    assert result is None


def test_structured_research_returns_none_when_pick_urls_fails(monkeypatch) -> None:
    monkeypatch.setattr(research.pipeline, "generate_search_queries", lambda llm, item: ["q"])
    monkeypatch.setattr(research.pipeline, "pick_urls", lambda llm, item, results: _raise(RuntimeError("fail")))
    monkeypatch.setattr(research.pipeline, "web_search", lambda q: [{"title": "T", "url": "https://x.com", "snippet": ""}])
    item = SoftwareItem(id="com.example.app", name="App", kind="application", source=SourceKind.APPLICATION, current_version="1.0")
    result = research_application_update(_dummy_llm(), item)
    assert result is None


def test_structured_research_returns_none_when_no_urls_picked(monkeypatch) -> None:
    monkeypatch.setattr(research.pipeline, "generate_search_queries", lambda llm, item: ["q"])
    monkeypatch.setattr(research.pipeline, "pick_urls", lambda llm, item, results: [])
    monkeypatch.setattr(research.pipeline, "web_search", lambda q: [{"title": "T", "url": "https://x.com", "snippet": ""}])
    item = SoftwareItem(id="com.example.app", name="App", kind="application", source=SourceKind.APPLICATION, current_version="1.0")
    result = research_application_update(_dummy_llm(), item)
    assert result is None


def test_structured_research_returns_none_when_extract_fails(monkeypatch) -> None:
    monkeypatch.setattr(research.pipeline, "generate_search_queries", lambda llm, item: ["q"])
    monkeypatch.setattr(research.pipeline, "pick_urls", lambda llm, item, results: ["https://x.com"])
    monkeypatch.setattr(research.pipeline, "extract_version", lambda llm, item, content: _raise(RuntimeError("fail")))
    monkeypatch.setattr(research.pipeline, "web_search", lambda q: [{"title": "T", "url": "https://x.com", "snippet": ""}])
    monkeypatch.setattr(research.pipeline, "web_fetch_batch", lambda urls: dict.fromkeys(urls, "content"))
    item = SoftwareItem(id="com.example.app", name="App", kind="application", source=SourceKind.APPLICATION, current_version="1.0")
    result = research_application_update(_dummy_llm(), item)
    assert result is None


# --- _make_candidate ---


def test_make_candidate_app_store_command() -> None:
    item = SoftwareItem(id="com.example.app", name="App", kind="application", source=SourceKind.APP_STORE, current_version="1.0")
    c = research._make_candidate(item, "2.0", source="itunes", app_store_id=99999)
    assert c.command == ["open", "macappstore://apps.apple.com/app/id99999"]
    assert c.can_auto_update is True


def test_make_candidate_homebrew_formula_command() -> None:
    item = SoftwareItem(id="node", name="node", kind="formula", source=SourceKind.HOMEBREW_FORMULA, current_version="20.0.0")
    c = research._make_candidate(item, "22.0.0")
    assert c.command == ["brew", "upgrade", "node"]
    assert c.can_auto_update is True


def test_make_candidate_homebrew_cask_command() -> None:
    item = SoftwareItem(id="google-chrome", name="google-chrome", kind="cask", source=SourceKind.HOMEBREW_CASK, current_version="120.0")
    c = research._make_candidate(item, "121.0")
    assert c.command == ["brew", "upgrade", "--cask", "google-chrome"]
    assert c.can_auto_update is True


def test_make_candidate_local_build_action() -> None:
    item = SoftwareItem(id="com.example.tool", name="Tool", kind="application", source=SourceKind.LOCAL_BUILD, current_version="0.3.0")
    c = research._make_candidate(item, "0.4.0")
    assert c.recommended_action is None
    assert c.can_auto_update is False


def test_make_candidate_defaults_none() -> None:
    item = SoftwareItem(id="com.example.app", name="App", kind="application", source=SourceKind.APPLICATION, current_version="1.0")
    c = research._make_candidate(item, "2.0", result=ResearchResult(confidence="high"))
    assert c.risk_level is None
    assert c.recommended_action is None


# --- _is_newer fallback paths ---


def test_is_newer_with_v_prefix() -> None:
    assert _is_newer("v1.0.0", "v2.0.0")


def test_is_newer_with_non_standard_versions() -> None:
    assert _is_newer("1.2.3beta", "1.2.4beta")


def test_is_newer_digits_only_fallback() -> None:
    assert _is_newer("build-2024.01", "build-2024.02")


# --- _normalize ---


def test_normalize_strips_v_prefix() -> None:
    assert _normalize("v1.2.3") == "1.2.3"
    assert _normalize("V4.0.0") == "4.0.0"


def test_normalize_strips_parenthetical() -> None:
    assert _normalize("1.2.3 (beta)") == "1.2.3"


def test_normalize_strips_space_suffix() -> None:
    assert _normalize("1.2.3 build 42") == "1.2.3"


def test_normalize_leading_whitespace() -> None:
    assert _normalize("  1.2.3") == "1.2.3"


# --- _digits_only ---


def test_digits_only_keeps_numbers_and_dots() -> None:
    assert _digits_only("1.2.3beta4") == "1.2.34"


def test_digits_only_no_digits() -> None:
    assert _digits_only("abc") == ""


# --- JSON helpers ---


class TestEnsureList:
    def test_list_of_ints(self) -> None:
        assert _ensure_list([1, 2]) == ["1", "2"]

    def test_single_string(self) -> None:
        assert _ensure_list("foo") == ["foo"]

    def test_none(self) -> None:
        assert _ensure_list(None) == []

    def test_empty_list(self) -> None:
        assert _ensure_list([]) == []


class TestParseJsonListError:
    def test_returns_empty_on_malformed(self) -> None:
        assert _parse_json_list("not json") == []

    def test_returns_empty_on_unexpected_type(self) -> None:
        assert _parse_json_list('{"key": "val"}') == []


class TestParseJsonObjectError:
    def test_returns_empty_on_malformed(self) -> None:
        assert _parse_json_object("not json") == {}

    def test_returns_empty_on_array(self) -> None:
        assert _parse_json_object("[1, 2]") == {}


class TestExtractJson:
    def test_strips_markdown_fence(self) -> None:
        result = _extract_json('```json\n{"key":"val"}\n```')
        assert result == '{"key":"val"}'

    def test_strips_tick_fence_only(self) -> None:
        result = _extract_json('```\n{"key":"val"}\n```')
        assert result == '{"key":"val"}'

    def test_extracts_json_from_text(self) -> None:
        result = _extract_json('prefix text {"key":"val"} suffix')
        assert result == '{"key":"val"}'

    def test_extracts_nested_json(self) -> None:
        result = _extract_json('text {"outer": {"inner": 1}} more')
        assert '"outer"' in result

    def test_returns_original_when_no_json_found(self) -> None:
        result = _extract_json("just plain text")
        assert result == "just plain text"
