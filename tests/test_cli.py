from __future__ import annotations

import json
from pathlib import Path

import typer

from checkupgrade.cli import _ADVICE_CACHE, _print_advise_result, update
from checkupgrade.models import PluginScanResult, ScanResult, SoftwareItem, SourceKind, SystemProfile, UpdateCandidate


def test_print_advise_result_shows_ignored_count(capsys) -> None:
    system = SystemProfile(os_name="macOS", os_version="15.0", arch="arm64", applications_paths=["/Applications"])
    result = ScanResult(system=system)

    _print_advise_result(result, researched_ids=set(), ignored_count=3)

    captured = capsys.readouterr()
    assert "3 app(s) ignored" in captured.out


def test_print_advise_result_no_ignored_shows_nothing(capsys) -> None:
    system = SystemProfile(os_name="macOS", os_version="15.0", arch="arm64", applications_paths=["/Applications"])
    result = ScanResult(system=system)

    _print_advise_result(result, researched_ids=set(), ignored_count=0)

    captured = capsys.readouterr()
    assert "ignored" not in captured.out


def _write_cache(tmp_path: Path, candidates: list[dict]) -> Path:
    cache = tmp_path / "last_advice.json"
    system = {"os_name": "macOS", "os_version": "15.0", "arch": "arm64", "applications_paths": []}
    plugin_results = {"applications": {"items": [], "candidates": candidates, "skipped": []}}
    cache.write_text(json.dumps({"system": system, "plugin_results": plugin_results}))
    return cache


def _brew_candidate_dict() -> dict:
    return {
        "item": {"id": "node", "name": "node", "kind": "formula", "source": "brew", "current_version": "20.0.0"},
        "latest_version": "22.0.0",
        "release_notes": None,
        "dependency_impact": {},
        "risk_level": "low",
        "ai_summary": None,
        "recommended_action": "Update",
        "can_auto_update": True,
        "command": ["brew", "upgrade", "node"],
        "evidence": [],
    }


def _manual_candidate_dict(path: str | None = None) -> dict:
    return {
        "item": {
            "id": "com.example.app",
            "name": "Example",
            "kind": "application",
            "source": "application",
            "current_version": "1.0",
            "path": path,
        },
        "latest_version": "2.0",
        "release_notes": None,
        "dependency_impact": {},
        "risk_level": "unknown",
        "ai_summary": None,
        "recommended_action": "Manual check",
        "can_auto_update": False,
        "command": [],
        "evidence": ["Source: llm"],
    }


def test_update_auto_runs_command(monkeypatch, tmp_path: Path) -> None:
    cache = _write_cache(tmp_path, [_brew_candidate_dict()])
    monkeypatch.setattr("checkupgrade.cli._ADVICE_CACHE", cache)

    ran = []
    monkeypatch.setattr("checkupgrade.cli.subprocess.run", lambda cmd, **kw: ran.append(cmd))
    monkeypatch.setattr("checkupgrade.cli.typer.confirm", lambda *a, **kw: True)

    update(only=None)

    assert len(ran) == 1
    assert ran[0] == ["brew", "upgrade", "node"]


def test_update_auto_skipped_on_no(monkeypatch, tmp_path: Path) -> None:
    cache = _write_cache(tmp_path, [_brew_candidate_dict()])
    monkeypatch.setattr("checkupgrade.cli._ADVICE_CACHE", cache)

    ran = []
    monkeypatch.setattr("checkupgrade.cli.subprocess.run", lambda cmd, **kw: ran.append(cmd))
    monkeypatch.setattr("checkupgrade.cli.typer.confirm", lambda *a, **kw: False)

    update(only=None)

    assert len(ran) == 0


def test_update_manual_opens_app_on_confirm(monkeypatch, tmp_path: Path) -> None:
    app_path = "/Applications/Example.app"
    cache = _write_cache(tmp_path, [_manual_candidate_dict(path=app_path)])
    monkeypatch.setattr("checkupgrade.cli._ADVICE_CACHE", cache)

    ran = []
    monkeypatch.setattr("checkupgrade.cli.subprocess.run", lambda cmd, **kw: ran.append(cmd))
    monkeypatch.setattr("checkupgrade.cli.typer.confirm", lambda *a, **kw: True)

    update(only=None)

    assert len(ran) == 1
    assert ran[0] == ["open", app_path]


def test_update_manual_skipped_on_no_confirm(monkeypatch, tmp_path: Path) -> None:
    cache = _write_cache(tmp_path, [_manual_candidate_dict(path="/Applications/Example.app")])
    monkeypatch.setattr("checkupgrade.cli._ADVICE_CACHE", cache)

    confirm_calls = []
    monkeypatch.setattr("checkupgrade.cli.typer.confirm", lambda *a, **kw: confirm_calls.append(a[0]) or False)

    update(only=None)

    # Only "Proceed?" should be asked, "Open app for update?" never reached
    assert len(confirm_calls) == 1


def test_update_filter_by_id(monkeypatch, tmp_path: Path) -> None:
    cache = _write_cache(tmp_path, [_brew_candidate_dict(), _manual_candidate_dict()])
    monkeypatch.setattr("checkupgrade.cli._ADVICE_CACHE", cache)

    ran = []
    monkeypatch.setattr("checkupgrade.cli.subprocess.run", lambda cmd, **kw: ran.append(cmd))
    monkeypatch.setattr("checkupgrade.cli.typer.confirm", lambda *a, **kw: True)

    update(only="node")

    assert len(ran) == 1
    assert ran[0] == ["brew", "upgrade", "node"]


def test_update_no_cache_exits(monkeypatch, tmp_path: Path) -> None:
    cache = tmp_path / "nonexistent.json"
    monkeypatch.setattr("checkupgrade.cli._ADVICE_CACHE", cache)

    import pytest
    with pytest.raises(typer.Exit):
        update(only=None)
