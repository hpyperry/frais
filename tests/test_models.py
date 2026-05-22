from __future__ import annotations

from frais.models import (
    DependencyImpact,
    PluginScanResult,
    ResearchResult,
    ScanResult,
    SoftwareItem,
    SourceKind,
    SystemProfile,
    UpdateCandidate,
)


# --- SoftwareItem round-trip ---


def test_software_item_to_dict_from_dict() -> None:
    original = SoftwareItem(
        id="com.example.app",
        name="MyApp",
        kind="application",
        source=SourceKind.APPLICATION,
        current_version="1.0",
        path="/Applications/MyApp.app",
        metadata={"bundle": "com.example.app"},
    )
    data = original.to_dict()
    restored = SoftwareItem.from_dict(data)
    assert restored.id == original.id
    assert restored.name == original.name
    assert restored.source == original.source
    assert restored.current_version == original.current_version


# --- UpdateCandidate round-trip ---


def test_update_candidate_to_dict_from_dict() -> None:
    item = SoftwareItem(id="com.example.app", name="App", kind="application", source=SourceKind.APPLICATION, current_version="1.0")
    original = UpdateCandidate(
        item=item,
        latest_version="2.0",
        release_notes="Bug fixes",
        risk_level="low",
        ai_summary="建议更新",
        recommended_action="Update",
        can_auto_update=False,
        command=[],
        evidence=["Source: llm"],
    )
    data = original.to_dict()
    restored = UpdateCandidate.from_dict(data)
    assert restored.latest_version == "2.0"
    assert restored.ai_summary == "建议更新"
    assert restored.item.name == "App"


# --- PluginScanResult ---


def test_plugin_scan_result_to_dict() -> None:
    item = SoftwareItem(id="com.example.app", name="App", kind="application", source=SourceKind.APPLICATION, current_version="1.0")
    pr = PluginScanResult(items=[item], candidates=[], skipped=["reason"])
    data = pr.to_dict()
    assert len(data["items"]) == 1
    assert data["skipped"] == ["reason"]


# --- ScanResult aggregates ---


def test_scan_result_all_candidates() -> None:
    item_a = SoftwareItem(id="a", name="A", kind="app", source=SourceKind.APPLICATION, current_version="1.0")
    item_b = SoftwareItem(id="b", name="B", kind="app", source=SourceKind.APPLICATION, current_version="2.0")
    c_a = UpdateCandidate(item=item_a, latest_version="2.0")
    c_b = UpdateCandidate(item=item_b, latest_version="3.0")
    system = SystemProfile(os_name="macOS", os_version="15.0", arch="arm64", applications_paths=["/Applications"])
    result = ScanResult(system=system, plugin_results={
        "apps": PluginScanResult(items=[item_a], candidates=[c_a]),
        "brew": PluginScanResult(items=[item_b], candidates=[c_b]),
    })
    assert len(result.all_candidates) == 2


# --- DependencyImpact ---


def test_dependency_impact_round_trip() -> None:
    original = DependencyImpact(used_by=["pkg-a"], depends_on=["pkg-b"], impact_level="low")
    data = original.to_dict()
    restored = DependencyImpact.from_dict(data)
    assert restored.used_by == ["pkg-a"]
    assert restored.impact_level == "low"


# --- SystemProfile ---


def test_system_profile_to_dict() -> None:
    sp = SystemProfile(os_name="macOS", os_version="15.0", arch="arm64", applications_paths=["/Applications"])
    data = sp.to_dict()
    assert data["os_name"] == "macOS"
    assert data["arch"] == "arm64"
