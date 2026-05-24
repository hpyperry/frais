"""UpdateCandidate construction from research results."""

from ....models import ResearchResult, SoftwareItem, SourceKind, UpdateCandidate


def _make_candidate(
    item: SoftwareItem,
    latest_version: str,
    result: ResearchResult | None = None,
    source: str = "llm",
    app_store_id: int | None = None,
) -> UpdateCandidate:
    can_auto = item.source not in {SourceKind.LOCAL_BUILD, SourceKind.UNKNOWN}
    action = "Update" if can_auto else "Rebuild" if item.source == SourceKind.LOCAL_BUILD else "Manual check"
    command: list[str] = []
    if item.source == SourceKind.APP_STORE and app_store_id:
        command = ["open", f"macappstore://apps.apple.com/app/id{app_store_id}"]
    elif item.source == SourceKind.HOMEBREW_FORMULA:
        command = ["brew", "upgrade", item.name]
    elif item.source == SourceKind.HOMEBREW_CASK:
        command = ["brew", "upgrade", "--cask", item.name]
    candidate = UpdateCandidate(
        item=item,
        latest_version=latest_version,
        release_notes=result.release_notes if result else None,
        recommended_action=action,
        can_auto_update=bool(command),
        command=command,
        evidence=result.evidence if result else [f"Source: {source}"],
        risk_level="unknown" if (not result or result.confidence != "high") else "low",
    )
    return candidate
