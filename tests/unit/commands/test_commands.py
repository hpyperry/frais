from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer

from frais.commands._scan_core import _save_cache, run_scan_phase
from frais.commands.summarize import summarize
from frais.commands.update import update
from frais.models import (
    PluginScanResult,
    ScanResult,
    SoftwareItem,
    SourceKind,
    SystemProfile,
    UpdateCandidate,
)

# --- _save_cache ---


def test_save_cache_writes_json(tmp_path: Path) -> None:
    cache = tmp_path / "cache.json"
    item = SoftwareItem(id="a", name="A", kind="app", source=SourceKind.APPLICATION, current_version="1.0")
    system = SystemProfile(os_name="macOS", os_version="15.0", arch="arm64", applications_paths=["/Apps"])
    result = ScanResult(system=system, plugin_results={
        "apps": PluginScanResult(items=[item], candidates=[]),
    })
    _save_cache(result, cache)
    assert cache.exists()
    data = json.loads(cache.read_text())
    assert data["system"]["os_name"] == "macOS"


# --- run_scan_phase json mode ---


def test_run_scan_phase_json_mode(monkeypatch) -> None:
    system = SystemProfile(os_name="macOS", os_version="15.0", arch="arm64", applications_paths=["/Apps"])
    item = SoftwareItem(id="a", name="A", kind="app", source=SourceKind.APPLICATION, current_version="1.0")
    pr = PluginScanResult(items=[item], candidates=[])

    def fake_run_scan(plugins, system, *, show_all=False, jobs=10, on_plugin_progress=None):
        return ScanResult(system=system, plugin_results={"test": pr})

    monkeypatch.setattr("frais.coordinator.run_scan", fake_run_scan)
    monkeypatch.setattr("frais.ignore_filter.load_ignored", lambda: set())

    result, ignored_count, scan_elapsed = run_scan_phase(
        {"test": _fake_plugin()}, system, json_output=True,
    )
    assert ignored_count == 0
    assert scan_elapsed == {}
    assert result.plugin_results["test"].items == [item]


def test_run_scan_phase_json_mode_with_ignore(monkeypatch) -> None:
    system = SystemProfile(os_name="macOS", os_version="15.0", arch="arm64", applications_paths=["/Apps"])
    item_a = SoftwareItem(id="a", name="A", kind="app", source=SourceKind.APPLICATION, current_version="1.0")
    item_b = SoftwareItem(id="b", name="B", kind="app", source=SourceKind.APPLICATION, current_version="2.0")
    cand_a = UpdateCandidate(item=item_a, latest_version="2.0")
    cand_b = UpdateCandidate(item=item_b, latest_version="3.0")
    pr = PluginScanResult(items=[item_a, item_b], candidates=[cand_a, cand_b])

    def fake_run_scan(plugins, system, *, show_all=False, jobs=10, on_plugin_progress=None):
        return ScanResult(system=system, plugin_results={"test": pr})

    monkeypatch.setattr("frais.coordinator.run_scan", fake_run_scan)
    monkeypatch.setattr("frais.ignore_filter.load_ignored", lambda: {"a"})

    result, ignored_count, _ = run_scan_phase(
        {"test": _fake_plugin()}, system, json_output=True,
    )
    assert ignored_count == 1
    assert len(result.plugin_results["test"].candidates) == 1
    assert result.plugin_results["test"].candidates[0].item.id == "b"


def test_run_scan_phase_json_mode_saves_cache(monkeypatch, tmp_path: Path) -> None:
    system = SystemProfile(os_name="macOS", os_version="15.0", arch="arm64", applications_paths=["/Apps"])
    item = SoftwareItem(id="a", name="A", kind="app", source=SourceKind.APPLICATION, current_version="1.0")
    pr = PluginScanResult(items=[item], candidates=[])

    def fake_run_scan(plugins, system, *, show_all=False, jobs=10, on_plugin_progress=None):
        return ScanResult(system=system, plugin_results={"test": pr})

    monkeypatch.setattr("frais.coordinator.run_scan", fake_run_scan)
    monkeypatch.setattr("frais.ignore_filter.load_ignored", lambda: set())

    cache = tmp_path / "cache.json"
    run_scan_phase({"test": _fake_plugin()}, system, json_output=True, cache_path=cache)
    assert cache.exists()


# --- summarize command ---


def test_summarize_no_cache_exits(monkeypatch, tmp_path: Path) -> None:
    cache = tmp_path / "nonexistent.json"
    monkeypatch.setattr("frais.commands.summarize.ADVICE_CACHE", cache)
    with pytest.raises(typer.Exit):
        summarize(item_id="com.example.app")


def test_summarize_candidate_not_found(monkeypatch, tmp_path: Path) -> None:
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps({
        "system": {"os_name": "macOS", "os_version": "15.0", "arch": "arm64", "applications_paths": []},
        "plugin_results": {"applications": {"items": [], "candidates": [], "skipped": []}},
    }))
    monkeypatch.setattr("frais.commands.summarize.ADVICE_CACHE", cache)
    with pytest.raises(typer.Exit):
        summarize(item_id="com.example.app")


def test_summarize_success(monkeypatch, tmp_path: Path) -> None:
    cache = tmp_path / "cache.json"
    candidate_dict = {
        "item": {"id": "com.example.app", "name": "Example", "kind": "application",
                 "source": "application", "current_version": "1.0"},
        "latest_version": "2.0", "release_notes": None, "dependency_impact": {},
        "risk_level": "low", "ai_summary": None, "recommended_action": "Update",
        "can_auto_update": False, "command": [], "evidence": [],
    }
    cache.write_text(json.dumps({
        "system": {"os_name": "macOS", "os_version": "15.0", "arch": "arm64", "applications_paths": []},
        "plugin_results": {"applications": {"items": [], "candidates": [candidate_dict], "skipped": []}},
    }))
    monkeypatch.setattr("frais.commands.summarize.ADVICE_CACHE", cache)
    monkeypatch.setattr("frais.commands.summarize.require_config", lambda: _fake_llm_config())

    class FakePlugin:
        name = "applications"
        def summarize(self, llm, candidate):
            return "建议更新"

    monkeypatch.setattr("frais.plugins.registry.all_plugins", lambda: {"applications": FakePlugin()})

    summarize(item_id="com.example.app")


# --- update command edge cases ---


def test_update_empty_cache(monkeypatch, tmp_path: Path) -> None:
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps({
        "system": {"os_name": "macOS", "os_version": "15.0", "arch": "arm64", "applications_paths": []},
        "plugin_results": {},
    }))
    monkeypatch.setattr("frais.commands.update.ADVICE_CACHE", cache)
    update(only=None)


# --- coordinator: run_scan error ---


def test_run_scan_handles_exception(monkeypatch) -> None:
    from frais.coordinator import run_scan

    system = SystemProfile(os_name="macOS", os_version="15.0", arch="arm64", applications_paths=["/Apps"])

    class FailingPlugin:
        name = "fail"
        scan_steps = ["failing"]
        def scan(self, system, on_progress=None, max_workers=10):
            raise RuntimeError("boom")

    result = run_scan({"fail": FailingPlugin()}, system)
    assert "fail" in result.plugin_results
    assert result.plugin_results["fail"].skipped == ["boom"]


# --- coordinator: run_summaries ---


def test_run_summaries_empty(monkeypatch) -> None:
    from frais.coordinator import run_summaries
    run_summaries(None, [], {}, {})


def test_run_summaries_calls_plugin(monkeypatch) -> None:
    from frais.coordinator import run_summaries

    item = SoftwareItem(id="a", name="A", kind="app", source=SourceKind.APPLICATION, current_version="1.0")
    candidate = UpdateCandidate(item=item, latest_version="2.0")

    calls = []
    class FakePlugin:
        def summarize(self, llm, c):
            calls.append(c)
            return "summary"

    run_summaries(None, [candidate], {id(candidate): "test"}, {"test": FakePlugin()}, max_workers=1)
    assert len(calls) == 1


def test_run_summaries_handles_exception(monkeypatch) -> None:
    from frais.coordinator import run_summaries

    item = SoftwareItem(id="a", name="A", kind="app", source=SourceKind.APPLICATION, current_version="1.0")
    candidate = UpdateCandidate(item=item, latest_version="2.0")

    class FailingPlugin:
        def summarize(self, llm, c):
            raise RuntimeError("fail")

    # Should not raise
    run_summaries(None, [candidate], {id(candidate): "test"}, {"test": FailingPlugin()}, max_workers=1)


def test_run_summaries_with_progress(monkeypatch) -> None:
    from frais.coordinator import run_summaries

    item = SoftwareItem(id="a", name="A", kind="app", source=SourceKind.APPLICATION, current_version="1.0")
    candidate = UpdateCandidate(item=item, latest_version="2.0")

    advances = []
    class FakePlugin:
        def summarize(self, llm, c):
            return "ok"

    run_summaries(None, [candidate], {id(candidate): "test"}, {"test": FakePlugin()},
                  max_workers=1, on_progress=lambda: advances.append(1))
    assert len(advances) == 1


# --- helpers ---


class _fake_plugin:
    name = "test"
    scan_steps = ["dummy step"]

    def scan(self, system, on_progress=None, max_workers=10):
        return PluginScanResult(items=[], candidates=[])


class _fake_llm_config:
    is_ready = True
    provider = type("P", (), {
        "id": "deepseek",
        "name": "deepseek",
        "base_url": "https://api.deepseek.com",
        "models": [type("M", (), {"id": "deepseek-v4-flash", "supports_thinking": True})()],
        "protocols": ["openai"],
        "web_search_protocols": [],
    })()
    model = "deepseek-v4-flash"
    api_key = "sk-test"
    api_key_source = None
    protocol = "openai"
    url = ""
