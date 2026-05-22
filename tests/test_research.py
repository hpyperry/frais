from __future__ import annotations

from frais.models import ResearchResult, SoftwareItem, SourceKind, UpdateCandidate
from frais.plugins.applications import _research as research
from frais.plugins.applications._research import _digits_only, _is_newer, _normalize, research_application_update


class FakeAgent:
    def generate_search_queries(self, item):
        return ["Tool macOS latest version"]

    def pick_urls(self, item, search_results):
        return ["https://github.com/example/tool/releases"]

    def extract_version(self, item, fetched_content):
        return ResearchResult(
            latest_version="0.4.0",
            confidence="high",
            evidence=["https://github.com/example/tool/releases/tag/v0.4.0"],
            release_notes="fixes",
        )

    def summarize_candidate(self, candidate):
        return "发现上游新版本，建议重新构建。"


def test_local_build_can_be_update_candidate(monkeypatch) -> None:
    # Mock web_search and web_fetch_batch to avoid network calls
    monkeypatch.setattr(research, "web_search", lambda q: [{"title": "Tool", "url": "https://github.com/example/tool/releases", "snippet": ""}])
    monkeypatch.setattr(research, "web_fetch_batch", lambda urls: {u: "Tag: v0.4.0" for u in urls})

    item = SoftwareItem(
        id="com.example.tool",
        name="Tool",
        kind="application",
        source=SourceKind.LOCAL_BUILD,
        current_version="0.3.0",
    )

    candidate = research.research_application_update(FakeAgent(), item)

    assert candidate is not None
    assert candidate.latest_version == "0.4.0"
    assert candidate.recommended_action == "Rebuild"
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


# --- attach_ai_summaries ---


def _make_test_candidate(name: str = "TestApp") -> UpdateCandidate:
    item = SoftwareItem(
        id=f"com.example.{name.lower()}",
        name=name,
        kind="application",
        source=SourceKind.APPLICATION,
        current_version="1.0",
    )
    return UpdateCandidate(item=item, latest_version="2.0")


# --- research_application_update iTunes fast path ---


def test_research_app_store_returns_candidate_when_newer(monkeypatch) -> None:
    monkeypatch.setattr(research, "check_app_store_version", lambda item: ("2.0", 12345))
    item = SoftwareItem(id="com.example.app", name="App", kind="application", source=SourceKind.APP_STORE, current_version="1.0")
    result = research_application_update(FakeAgent(), item)
    assert result is not None
    assert result.latest_version == "2.0"
    assert result.command == ["open", "macappstore://apps.apple.com/app/id12345"]


def test_research_app_store_returns_none_when_up_to_date(monkeypatch) -> None:
    monkeypatch.setattr(research, "check_app_store_version", lambda item: ("1.0", None))
    item = SoftwareItem(id="com.example.app", name="App", kind="application", source=SourceKind.APP_STORE, current_version="1.0")
    result = research_application_update(FakeAgent(), item)
    assert result is None


def test_research_app_store_falls_through_when_no_itunes_result(monkeypatch) -> None:
    # FakeAgent returns latest_version "0.4.0" — make current older so it's newer
    monkeypatch.setattr(research, "check_app_store_version", lambda item: (None, None))
    monkeypatch.setattr(research, "web_search", lambda q: [{"title": "T", "url": "https://example.com", "snippet": ""}])
    monkeypatch.setattr(research, "web_fetch_batch", lambda urls: {u: "v0.4.0" for u in urls})
    item = SoftwareItem(id="com.example.app", name="App", kind="application", source=SourceKind.APP_STORE, current_version="0.3.0")
    result = research_application_update(FakeAgent(), item)
    assert result is not None
    assert result.latest_version == "0.4.0"


# --- _llm_structured_research failure paths ---


class _FailingQueriesAgent:
    def generate_search_queries(self, item):
        raise RuntimeError("network error")

    def pick_urls(self, item, results):
        return []

    def extract_version(self, item, fetched):
        return ResearchResult()


def test_structured_research_returns_none_when_generate_queries_fails(monkeypatch) -> None:
    item = SoftwareItem(id="com.example.app", name="App", kind="application", source=SourceKind.APPLICATION, current_version="1.0")
    result = research_application_update(_FailingQueriesAgent(), item)
    assert result is None


class _EmptyQueriesAgent:
    def generate_search_queries(self, item):
        return []

    def pick_urls(self, item, results):
        return []

    def extract_version(self, item, fetched):
        return ResearchResult()


def test_structured_research_returns_none_when_no_queries(monkeypatch) -> None:
    item = SoftwareItem(id="com.example.app", name="App", kind="application", source=SourceKind.APPLICATION, current_version="1.0")
    result = research_application_update(_EmptyQueriesAgent(), item)
    assert result is None


class _FailingPickUrlsAgent:
    def generate_search_queries(self, item):
        return ["q"]

    def pick_urls(self, item, results):
        raise RuntimeError("fail")

    def extract_version(self, item, fetched):
        return ResearchResult()


def test_structured_research_returns_none_when_pick_urls_fails(monkeypatch) -> None:
    monkeypatch.setattr(research, "web_search", lambda q: [{"title": "T", "url": "https://x.com", "snippet": ""}])
    item = SoftwareItem(id="com.example.app", name="App", kind="application", source=SourceKind.APPLICATION, current_version="1.0")
    result = research_application_update(_FailingPickUrlsAgent(), item)
    assert result is None


class _EmptyPickUrlsAgent:
    def generate_search_queries(self, item):
        return ["q"]

    def pick_urls(self, item, results):
        return []

    def extract_version(self, item, fetched):
        return ResearchResult()


def test_structured_research_returns_none_when_no_urls_picked(monkeypatch) -> None:
    monkeypatch.setattr(research, "web_search", lambda q: [{"title": "T", "url": "https://x.com", "snippet": ""}])
    item = SoftwareItem(id="com.example.app", name="App", kind="application", source=SourceKind.APPLICATION, current_version="1.0")
    result = research_application_update(_EmptyPickUrlsAgent(), item)
    assert result is None


class _FailingExtractAgent:
    def generate_search_queries(self, item):
        return ["q"]

    def pick_urls(self, item, results):
        return ["https://x.com"]

    def extract_version(self, item, fetched):
        raise RuntimeError("fail")


def test_structured_research_returns_none_when_extract_fails(monkeypatch) -> None:
    monkeypatch.setattr(research, "web_search", lambda q: [{"title": "T", "url": "https://x.com", "snippet": ""}])
    monkeypatch.setattr(research, "web_fetch_batch", lambda urls: {u: "content" for u in urls})
    item = SoftwareItem(id="com.example.app", name="App", kind="application", source=SourceKind.APPLICATION, current_version="1.0")
    result = research_application_update(_FailingExtractAgent(), item)
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
    assert c.recommended_action == "Rebuild"
    assert c.can_auto_update is False


def test_make_candidate_risk_level() -> None:
    item = SoftwareItem(id="com.example.app", name="App", kind="application", source=SourceKind.APPLICATION, current_version="1.0")
    c_high = research._make_candidate(item, "2.0", result=ResearchResult(confidence="high"))
    assert c_high.risk_level == "low"
    c_medium = research._make_candidate(item, "2.0", result=ResearchResult(confidence="medium"))
    assert c_medium.risk_level == "unknown"


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
