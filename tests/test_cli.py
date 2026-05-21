from __future__ import annotations

import json
from pathlib import Path

import typer

import pytest

from mise.cli import _ADVICE_CACHE, _print_advise_result, _select_plugins, update
from mise.models import ScanResult, SystemProfile


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
    monkeypatch.setattr("mise.cli._ADVICE_CACHE", cache)

    ran = []
    monkeypatch.setattr("mise.cli.subprocess.run", lambda cmd, **kw: ran.append(cmd))
    monkeypatch.setattr("mise.cli.typer.confirm", lambda *a, **kw: True)

    update(only=None)

    assert len(ran) == 1
    assert ran[0] == ["brew", "upgrade", "node"]


def test_update_auto_skipped_on_no(monkeypatch, tmp_path: Path) -> None:
    cache = _write_cache(tmp_path, [_brew_candidate_dict()])
    monkeypatch.setattr("mise.cli._ADVICE_CACHE", cache)

    ran = []
    monkeypatch.setattr("mise.cli.subprocess.run", lambda cmd, **kw: ran.append(cmd))
    monkeypatch.setattr("mise.cli.typer.confirm", lambda *a, **kw: False)

    update(only=None)

    assert len(ran) == 0


def test_update_manual_opens_app_on_confirm(monkeypatch, tmp_path: Path) -> None:
    app_path = "/Applications/Example.app"
    cache = _write_cache(tmp_path, [_manual_candidate_dict(path=app_path)])
    monkeypatch.setattr("mise.cli._ADVICE_CACHE", cache)

    ran = []
    monkeypatch.setattr("mise.cli.subprocess.run", lambda cmd, **kw: ran.append(cmd))
    monkeypatch.setattr("mise.cli.typer.confirm", lambda *a, **kw: True)

    update(only=None)

    assert len(ran) == 1
    assert ran[0] == ["open", app_path]


def test_update_manual_skipped_on_no_confirm(monkeypatch, tmp_path: Path) -> None:
    cache = _write_cache(tmp_path, [_manual_candidate_dict(path="/Applications/Example.app")])
    monkeypatch.setattr("mise.cli._ADVICE_CACHE", cache)

    confirm_calls = []
    monkeypatch.setattr("mise.cli.typer.confirm", lambda *a, **kw: confirm_calls.append(a[0]) or False)

    update(only=None)

    # Only "Proceed?" should be asked, "Open app for update?" never reached
    assert len(confirm_calls) == 1


def test_update_filter_by_id(monkeypatch, tmp_path: Path) -> None:
    cache = _write_cache(tmp_path, [_brew_candidate_dict(), _manual_candidate_dict()])
    monkeypatch.setattr("mise.cli._ADVICE_CACHE", cache)

    ran = []
    monkeypatch.setattr("mise.cli.subprocess.run", lambda cmd, **kw: ran.append(cmd))
    monkeypatch.setattr("mise.cli.typer.confirm", lambda *a, **kw: True)

    update(only="node")

    assert len(ran) == 1
    assert ran[0] == ["brew", "upgrade", "node"]


def test_update_no_cache_exits(monkeypatch, tmp_path: Path) -> None:
    cache = tmp_path / "nonexistent.json"
    monkeypatch.setattr("mise.cli._ADVICE_CACHE", cache)

    with pytest.raises(typer.Exit):
        update(only=None)


# --- _select_plugins with persistence ---


def test_select_plugins_apps_only_ignores_persistence(monkeypatch) -> None:
    monkeypatch.setattr("mise.plugins.config.load_plugins_config", lambda: {"applications": False})
    result = _select_plugins(apps_only=True, explicit=None)
    assert result == ["applications"]


def test_select_plugins_explicit_ignores_persistence(monkeypatch) -> None:
    monkeypatch.setattr("mise.plugins.config.load_plugins_config", lambda: {"homebrew": False})
    monkeypatch.setattr("mise.plugins.registry.all_plugins", lambda: {
        "homebrew": _fake_plugin("homebrew", True),
        "npm": _fake_plugin("npm", True),
    })
    result = _select_plugins(apps_only=False, explicit=["homebrew"])
    assert result == ["homebrew"]


def test_select_plugins_persisted_disable_removes_default_enabled(monkeypatch) -> None:
    monkeypatch.setattr("mise.plugins.config.load_plugins_config", lambda: {"homebrew": False, "npm": False})
    monkeypatch.setattr("mise.plugins.registry.all_plugins", lambda: {
        "applications": _fake_plugin("applications", True),
        "homebrew": _fake_plugin("homebrew", True),
        "npm": _fake_plugin("npm", True),
    })
    result = _select_plugins(apps_only=False, explicit=None)
    assert result == ["applications"]


def test_select_plugins_persisted_enable_adds_default_disabled(monkeypatch) -> None:
    monkeypatch.setattr("mise.plugins.config.load_plugins_config", lambda: {"custom": True})
    monkeypatch.setattr("mise.plugins.registry.all_plugins", lambda: {
        "applications": _fake_plugin("applications", True),
        "custom": _fake_plugin("custom", False),
    })
    result = _select_plugins(apps_only=False, explicit=None)
    assert "custom" in result


def test_select_plugins_uses_default_when_not_persisted(monkeypatch) -> None:
    monkeypatch.setattr("mise.plugins.config.load_plugins_config", lambda: {})
    monkeypatch.setattr("mise.plugins.registry.all_plugins", lambda: {
        "a": _fake_plugin("a", True),
        "b": _fake_plugin("b", False),
    })
    result = _select_plugins(apps_only=False, explicit=None)
    assert result == ["a"]


# --- plugins enable/disable CLI ---


def test_plugins_enable_persists(monkeypatch, capsys) -> None:
    from mise.cli import plugins_enable

    calls = {}
    def fake_save(name, enabled):
        calls["name"] = name
        calls["enabled"] = enabled
    monkeypatch.setattr("mise.plugins.config.init_plugins_config", lambda: None)
    monkeypatch.setattr("mise.plugins.config.save_plugin_state", fake_save)
    monkeypatch.setattr("mise.plugins.registry.all_plugins", lambda: {"homebrew": _fake_plugin("homebrew", True)})

    plugins_enable("homebrew")
    captured = capsys.readouterr()
    assert calls == {"name": "homebrew", "enabled": True}
    assert "enabled" in captured.out


def test_plugins_enable_unknown_plugin(monkeypatch) -> None:
    from mise.cli import plugins_enable

    monkeypatch.setattr("mise.plugins.config.init_plugins_config", lambda: None)
    monkeypatch.setattr("mise.plugins.config.save_plugin_state", lambda name, enabled: None)
    monkeypatch.setattr("mise.plugins.registry.all_plugins", lambda: {})

    with pytest.raises(typer.Exit):
        plugins_enable("nonexistent")


def test_plugins_disable_persists(monkeypatch, capsys) -> None:
    from mise.cli import plugins_disable

    calls = {}
    def fake_save(name, enabled):
        calls["name"] = name
        calls["enabled"] = enabled
    monkeypatch.setattr("mise.plugins.config.init_plugins_config", lambda: None)
    monkeypatch.setattr("mise.plugins.config.save_plugin_state", fake_save)
    monkeypatch.setattr("mise.plugins.registry.all_plugins", lambda: {"homebrew": _fake_plugin("homebrew", True)})

    plugins_disable("homebrew")
    captured = capsys.readouterr()
    assert calls == {"name": "homebrew", "enabled": False}
    assert "disabled" in captured.out


def test_plugins_disable_unknown_plugin(monkeypatch) -> None:
    from mise.cli import plugins_disable

    monkeypatch.setattr("mise.plugins.config.init_plugins_config", lambda: None)
    monkeypatch.setattr("mise.plugins.config.save_plugin_state", lambda name, enabled: None)
    monkeypatch.setattr("mise.plugins.registry.all_plugins", lambda: {})

    with pytest.raises(typer.Exit):
        plugins_disable("nonexistent")


# --- plugins list with persistence ---


def test_plugins_list_shows_persisted_state(monkeypatch, capsys) -> None:
    from mise.cli import plugins_list

    monkeypatch.setattr("mise.plugins.config.init_plugins_config", lambda: None)
    monkeypatch.setattr("mise.plugins.config.load_plugins_config", lambda: {"homebrew": False})
    monkeypatch.setattr("mise.plugins.registry.all_plugins", lambda: {
        "applications": _fake_plugin("applications", True),
        "homebrew": _fake_plugin("homebrew", True),
        "npm": _fake_plugin("npm", True, available=False),
    })

    plugins_list()
    captured = capsys.readouterr()
    assert "applications" in captured.out
    assert "homebrew" in captured.out
    assert "npm" in captured.out
    assert "disabled" in captured.out  # homebrew Effective = disabled


def test_plugins_list_uses_default_when_not_persisted(monkeypatch, capsys) -> None:
    from mise.cli import plugins_list

    monkeypatch.setattr("mise.plugins.config.init_plugins_config", lambda: None)
    monkeypatch.setattr("mise.plugins.config.load_plugins_config", lambda: {})
    monkeypatch.setattr("mise.plugins.registry.all_plugins", lambda: {
        "applications": _fake_plugin("applications", True),
    })

    plugins_list()
    captured = capsys.readouterr()
    assert "enabled" in captured.out


# --- _select_plugins edge cases ---


def test_select_plugins_silently_drops_unknown_names(monkeypatch) -> None:
    monkeypatch.setattr("mise.plugins.registry.all_plugins", lambda: {
        "applications": _fake_plugin("applications", True),
    })
    result = _select_plugins(apps_only=False, explicit=["applications", "nonexistent"])
    assert result == ["applications"]


# --- helpers ---


class _fake_plugin:
    def __init__(self, name: str, default: bool, available: bool = True):
        self.name = name
        self.enabled_by_default = default
        self._available = available

    def is_available(self) -> bool:
        return self._available
