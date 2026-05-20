from __future__ import annotations

from checkupgrade.models import SoftwareItem, SourceKind
from checkupgrade import research


class FakeAgent:
    def research_application(self, item):
        class Result:
            latest_version = "0.4.0"
            release_notes = "fixes"
            confidence = "high"
            evidence = ["https://github.com/example/tool/releases/tag/v0.4.0"]

        return Result()

    def summarize_candidate(self, candidate):
        return "发现上游新版本，建议重新构建。"


def test_local_build_can_be_update_candidate(monkeypatch) -> None:
    # Skip the GitHub fast path so the LLM path is used
    monkeypatch.setattr(research, "_try_github_fast_path", lambda item: None)
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
