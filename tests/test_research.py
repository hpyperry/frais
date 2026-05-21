from __future__ import annotations

from checkupgrade import research
from checkupgrade.models import ResearchResult, SoftwareItem, SourceKind
from checkupgrade.research import _is_newer


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
