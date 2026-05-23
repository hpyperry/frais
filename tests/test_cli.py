from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx
import typer

import pytest

from frais.cli import _ADVICE_CACHE, _configure_logging
from frais.commands import _split_plugins
from frais.commands.advise import _print_advise_result
from frais.commands.update import update
from frais.coordinator import select_plugins
from frais.plugins.applications._store import resolve_app_store_command
from frais.models import PluginScanResult, ScanResult, SoftwareItem, SourceKind, SystemProfile, UpdateCandidate


def test_print_advise_result_shows_ignored_count(capsys) -> None:
    system = SystemProfile(os_name="macOS", os_version="15.0", arch="arm64", applications_paths=["/Applications"])
    result = ScanResult(system=system)

    _print_advise_result(result, ignored_count=3)

    captured = capsys.readouterr()
    assert "3 app(s) ignored" in captured.out


def test_print_advise_result_no_ignored_shows_nothing(capsys) -> None:
    system = SystemProfile(os_name="macOS", os_version="15.0", arch="arm64", applications_paths=["/Applications"])
    result = ScanResult(system=system)

    _print_advise_result(result, ignored_count=0)

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
    monkeypatch.setattr("frais.cli._ADVICE_CACHE", cache)

    ran = []
    monkeypatch.setattr("frais.cli.subprocess.run", lambda cmd, **kw: ran.append(cmd))
    monkeypatch.setattr("frais.cli.typer.confirm", lambda *a, **kw: True)

    update(only=None)

    assert len(ran) == 1
    assert ran[0] == ["brew", "upgrade", "node"]


def test_update_auto_skipped_on_no(monkeypatch, tmp_path: Path) -> None:
    cache = _write_cache(tmp_path, [_brew_candidate_dict()])
    monkeypatch.setattr("frais.cli._ADVICE_CACHE", cache)

    ran = []
    monkeypatch.setattr("frais.cli.subprocess.run", lambda cmd, **kw: ran.append(cmd))
    monkeypatch.setattr("frais.cli.typer.confirm", lambda *a, **kw: False)

    update(only=None)
    assert ran == []


def test_update_manual_opens_app_on_confirm(monkeypatch, tmp_path: Path) -> None:
    app_path = "/Applications/Example.app"
    cache = _write_cache(tmp_path, [_manual_candidate_dict(path=app_path)])
    monkeypatch.setattr("frais.cli._ADVICE_CACHE", cache)

    ran = []
    monkeypatch.setattr("frais.cli.subprocess.run", lambda cmd, **kw: ran.append(cmd))
    monkeypatch.setattr("frais.cli.typer.confirm", lambda *a, **kw: True)

    update(only=None)

    assert len(ran) == 1
    assert ran[0] == ["open", app_path]


def test_update_manual_skipped_on_no_confirm(monkeypatch, tmp_path: Path) -> None:
    cache = _write_cache(tmp_path, [_manual_candidate_dict(path="/Applications/Example.app")])
    monkeypatch.setattr("frais.cli._ADVICE_CACHE", cache)

    confirm_calls = []
    monkeypatch.setattr("frais.cli.typer.confirm", lambda *a, **kw: confirm_calls.append(a[0]) or False)

    update(only=None)
    assert len(confirm_calls) == 1


def test_update_filter_by_id(monkeypatch, tmp_path: Path) -> None:
    cache = _write_cache(tmp_path, [_brew_candidate_dict(), _manual_candidate_dict()])
    monkeypatch.setattr("frais.cli._ADVICE_CACHE", cache)

    ran = []
    monkeypatch.setattr("frais.cli.subprocess.run", lambda cmd, **kw: ran.append(cmd))
    monkeypatch.setattr("frais.cli.typer.confirm", lambda *a, **kw: True)

    update(only="node")

    assert len(ran) == 1
    assert ran[0] == ["brew", "upgrade", "node"]


def test_update_no_cache_exits(monkeypatch, tmp_path: Path) -> None:
    cache = tmp_path / "nonexistent.json"
    monkeypatch.setattr("frais.cli._ADVICE_CACHE", cache)

    with pytest.raises(typer.Exit):
        update(only=None)


# --- select_plugins with persistence ---


def test_select_plugins_explicit_respects_disabled(monkeypatch) -> None:
    monkeypatch.setattr("frais.store.plugin_store.load_plugins_config", lambda: {"homebrew": False})
    monkeypatch.setattr("frais.plugins.registry.all_plugins", lambda: {
        "homebrew": _fake_plugin("homebrew", True),
        "npm": _fake_plugin("npm", True),
    })
    result = select_plugins(explicit=["homebrew"])
    assert list(result.keys()) == []  # homebrew is disabled


def test_select_plugins_persisted_disable_removes_default_enabled(monkeypatch) -> None:
    monkeypatch.setattr("frais.store.plugin_store.load_plugins_config", lambda: {"homebrew": False, "npm": False})
    monkeypatch.setattr("frais.plugins.registry.all_plugins", lambda: {
        "applications": _fake_plugin("applications", True),
        "homebrew": _fake_plugin("homebrew", True),
        "npm": _fake_plugin("npm", True),
    })
    result = select_plugins(explicit=None)
    assert list(result.keys()) == ["applications"]


def test_select_plugins_persisted_enable_adds_default_disabled(monkeypatch) -> None:
    monkeypatch.setattr("frais.store.plugin_store.load_plugins_config", lambda: {"custom": True})
    monkeypatch.setattr("frais.plugins.registry.all_plugins", lambda: {
        "applications": _fake_plugin("applications", True),
        "custom": _fake_plugin("custom", False),
    })
    result = select_plugins(explicit=None)
    assert "custom" in result


def test_select_plugins_uses_default_when_not_persisted(monkeypatch) -> None:
    monkeypatch.setattr("frais.store.plugin_store.load_plugins_config", lambda: {})
    monkeypatch.setattr("frais.plugins.registry.all_plugins", lambda: {
        "a": _fake_plugin("a", True),
        "b": _fake_plugin("b", False),
    })
    result = select_plugins(explicit=None)
    assert list(result.keys()) == ["a"]


# --- plugins enable/disable CLI ---


def test_plugins_enable_persists(monkeypatch, capsys) -> None:
    from frais.cli import plugins_enable

    calls = {}
    def fake_save(name, enabled):
        calls["name"] = name
        calls["enabled"] = enabled
    monkeypatch.setattr("frais.store.plugin_store.init_plugins_config", lambda: None)
    monkeypatch.setattr("frais.store.plugin_store.save_plugin_state", fake_save)
    monkeypatch.setattr("frais.plugins.registry.all_plugins", lambda: {"homebrew": _fake_plugin("homebrew", True)})

    plugins_enable("homebrew")
    captured = capsys.readouterr()
    assert calls == {"name": "homebrew", "enabled": True}
    assert "enabled" in captured.out


def test_plugins_enable_unknown_plugin(monkeypatch) -> None:
    from frais.cli import plugins_enable

    monkeypatch.setattr("frais.store.plugin_store.init_plugins_config", lambda: None)
    monkeypatch.setattr("frais.store.plugin_store.save_plugin_state", lambda name, enabled: None)
    monkeypatch.setattr("frais.plugins.registry.all_plugins", lambda: {})

    with pytest.raises(typer.Exit):
        plugins_enable("nonexistent")


def test_plugins_disable_persists(monkeypatch, capsys) -> None:
    from frais.cli import plugins_disable

    calls = {}
    def fake_save(name, enabled):
        calls["name"] = name
        calls["enabled"] = enabled
    monkeypatch.setattr("frais.store.plugin_store.init_plugins_config", lambda: None)
    monkeypatch.setattr("frais.store.plugin_store.save_plugin_state", fake_save)
    monkeypatch.setattr("frais.plugins.registry.all_plugins", lambda: {"homebrew": _fake_plugin("homebrew", True)})

    plugins_disable("homebrew")
    captured = capsys.readouterr()
    assert calls == {"name": "homebrew", "enabled": False}
    assert "disabled" in captured.out


def test_plugins_disable_unknown_plugin(monkeypatch) -> None:
    from frais.cli import plugins_disable

    monkeypatch.setattr("frais.store.plugin_store.init_plugins_config", lambda: None)
    monkeypatch.setattr("frais.store.plugin_store.save_plugin_state", lambda name, enabled: None)
    monkeypatch.setattr("frais.plugins.registry.all_plugins", lambda: {})

    with pytest.raises(typer.Exit):
        plugins_disable("nonexistent")


# --- plugins list with persistence ---


def test_plugins_list_shows_persisted_state(monkeypatch, capsys) -> None:
    from frais.cli import plugins_list

    monkeypatch.setattr("frais.store.plugin_store.init_plugins_config", lambda: None)
    monkeypatch.setattr("frais.store.plugin_store.load_plugins_config", lambda: {"homebrew": False})
    monkeypatch.setattr("frais.plugins.registry.all_plugins", lambda: {
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
    from frais.cli import plugins_list

    monkeypatch.setattr("frais.store.plugin_store.init_plugins_config", lambda: None)
    monkeypatch.setattr("frais.store.plugin_store.load_plugins_config", lambda: {})
    monkeypatch.setattr("frais.plugins.registry.all_plugins", lambda: {
        "applications": _fake_plugin("applications", True),
    })

    plugins_list()
    captured = capsys.readouterr()
    assert "enabled" in captured.out


# --- select_plugins edge cases ---


def test_select_plugins_drops_unknown_names(monkeypatch) -> None:
    monkeypatch.setattr("frais.plugins.registry.all_plugins", lambda: {
        "applications": _fake_plugin("applications", True),
    })
    result = select_plugins(explicit=["applications", "nonexistent"])
    assert list(result.keys()) == ["applications"]


# --- _split_plugins ---


def test_split_plugins_none() -> None:
    assert _split_plugins(None) is None


def test_split_plugins_empty_string() -> None:
    assert _split_plugins("") is None


def test_split_plugins_single() -> None:
    assert _split_plugins("homebrew") == ["homebrew"]


def test_split_plugins_comma_separated() -> None:
    assert _split_plugins("homebrew, npm , applications") == ["homebrew", "npm", "applications"]


# --- _resolve_app_store_command ---


def test_resolve_app_store_returns_command(monkeypatch) -> None:
    fake_resp = type("Resp", (), {"raise_for_status": lambda self: None, "json": lambda self: {"resultCount": 1, "results": [{"trackId": 12345}]}})()
    monkeypatch.setattr(httpx, "get", lambda url, **kw: fake_resp)
    item = SoftwareItem(id="com.example.app", name="App", kind="application", source=SourceKind.APP_STORE, current_version="1.0")
    cmd, can_auto = resolve_app_store_command(item)
    assert cmd == ["open", "macappstore://apps.apple.com/app/id12345"]
    assert can_auto is True


def test_resolve_app_store_no_results(monkeypatch) -> None:
    fake_resp = type("Resp", (), {"raise_for_status": lambda self: None, "json": lambda self: {"resultCount": 0}})()
    monkeypatch.setattr(httpx, "get", lambda url, **kw: fake_resp)
    item = SoftwareItem(id="com.example.app", name="App", kind="application", source=SourceKind.APP_STORE, current_version="1.0")
    cmd, can_auto = resolve_app_store_command(item)
    assert cmd == []
    assert can_auto is False


def test_resolve_app_store_http_error(monkeypatch) -> None:
    def raise_error(url, **kw):
        raise Exception("network error")
    monkeypatch.setattr(httpx, "get", raise_error)
    item = SoftwareItem(id="com.example.app", name="App", kind="application", source=SourceKind.APP_STORE, current_version="1.0")
    cmd, can_auto = resolve_app_store_command(item)
    assert cmd == []
    assert can_auto is False


# --- _print_advise_result show_all branches ---


def test_print_advise_result_show_all_up_to_date(capsys) -> None:
    item = SoftwareItem(id="com.example.ok", name="OkApp", kind="application", source=SourceKind.APPLICATION, current_version="2.0")
    pr = PluginScanResult(items=[item], candidates=[], skipped=[])
    system = SystemProfile(os_name="macOS", os_version="15.0", arch="arm64", applications_paths=["/Applications"])
    result = ScanResult(system=system, plugin_results={"applications": pr})

    _print_advise_result(result, ignored_count=0, show_all=True)

    captured = capsys.readouterr()
    assert "up to date" in captured.out


def test_print_advise_result_shows_skipped(capsys) -> None:
    pr = PluginScanResult(items=[], candidates=[], skipped=["brew not found"])
    system = SystemProfile(os_name="macOS", os_version="15.0", arch="arm64", applications_paths=["/Applications"])
    result = ScanResult(system=system, plugin_results={"homebrew": pr})

    _print_advise_result(result, ignored_count=0)

    captured = capsys.readouterr()
    assert "brew not found" in captured.out


def test_print_advise_result_shows_updates_section(capsys) -> None:
    item = SoftwareItem(id="com.example.app", name="App", kind="application", source=SourceKind.APPLICATION, current_version="1.0")
    candidate = UpdateCandidate(item=item, latest_version="2.0", recommended_action="Update")
    pr = PluginScanResult(items=[item], candidates=[candidate], skipped=[])
    system = SystemProfile(os_name="macOS", os_version="15.0", arch="arm64", applications_paths=["/Applications"])
    result = ScanResult(system=system, plugin_results={"applications": pr})

    _print_advise_result(result, ignored_count=0)

    captured = capsys.readouterr()
    assert "Updates available" in captured.out
    assert "2.0" in captured.out


# --- _configure_logging ---


def test_configure_logging_stderr_level_default(tmp_path) -> None:
    log_path = tmp_path / "test.log"
    _configure_logging(verbose=False, debug=False, log_file=str(log_path), no_log=False)
    root = logging.getLogger()
    stderr_handler = next(h for h in root.handlers if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler))
    assert stderr_handler.level == logging.ERROR


def test_configure_logging_stderr_level_verbose(tmp_path) -> None:
    log_path = tmp_path / "test.log"
    _configure_logging(verbose=True, debug=False, log_file=str(log_path), no_log=False)
    root = logging.getLogger()
    stderr_handler = next(h for h in root.handlers if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler))
    assert stderr_handler.level == logging.INFO


def test_configure_logging_stderr_level_debug(tmp_path) -> None:
    log_path = tmp_path / "test.log"
    _configure_logging(verbose=False, debug=True, log_file=str(log_path), no_log=False)
    root = logging.getLogger()
    stderr_handler = next(h for h in root.handlers if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler))
    assert stderr_handler.level == logging.DEBUG


def test_configure_logging_truncates_large_file(tmp_path) -> None:
    log_path = tmp_path / "big.log"
    log_path.write_text("x" * (6 * 1024 * 1024))  # 6MB > 5MB limit
    _configure_logging(verbose=False, debug=False, log_file=str(log_path), no_log=False)
    assert log_path.stat().st_size < 100


def test_configure_logging_no_log(tmp_path) -> None:
    log_path = tmp_path / "no_write.log"
    _configure_logging(verbose=False, debug=False, log_file=str(log_path), no_log=True)
    assert not log_path.exists()


# --- helpers ---


class _fake_plugin:
    def __init__(self, name: str, default: bool, available: bool = True):
        self.name = name
        self.enabled_by_default = default
        self._available = available

    def is_available(self) -> bool:
        return self._available


# --- JSON output tests ---


def test_doctor_json_output(monkeypatch, capsys) -> None:
    from frais.cli import doctor
    from frais.models import SystemProfile

    monkeypatch.setattr("frais.system.detect_system", lambda: SystemProfile(
        os_name="macOS", os_version="26.5", arch="arm64",
        applications_paths=["/Applications", "/Users/test/Applications"],
    ))
    monkeypatch.setattr("frais.plugins.registry.all_plugins", lambda: {
        "applications": _fake_plugin("applications", True, available=True),
        "homebrew": _fake_plugin("homebrew", False, available=False),
    })
    monkeypatch.setattr("frais.cli.load_config", lambda: None)

    doctor(json_output=True)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is True
    assert data["system"]["os_name"] == "macOS"
    assert data["system"]["os_version"] == "26.5"
    assert data["plugins"]["applications"]["available"] == "yes"
    assert data["plugins"]["homebrew"]["available"] == "no"
    assert data["llm"] is None


def test_doctor_json_output_with_llm(monkeypatch, capsys) -> None:
    from frais.cli import doctor
    from frais.models import SystemProfile

    monkeypatch.setattr("frais.system.detect_system", lambda: SystemProfile(
        os_name="macOS", os_version="15.0", arch="arm64",
        applications_paths=["/Applications"],
    ))
    monkeypatch.setattr("frais.plugins.registry.all_plugins", lambda: {})
    fake_provider = type("P", (), {"name": "DeepSeek", "id": "deepseek"})()
    fake_config = type("C", (), {
        "is_ready": True,
        "provider": fake_provider,
        "model": "deepseek-v4-flash",
        "api_key": "sk-12345678abcd",
    })()
    monkeypatch.setattr("frais.cli.load_config", lambda: fake_config)

    doctor(json_output=True)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["llm"]["configured"] is True
    assert data["llm"]["provider"] == "DeepSeek"
    assert data["llm"]["model"] == "deepseek-v4-flash"
    assert "abcd" in data["llm"]["key_suffix"]


def test_plugins_list_json_output(monkeypatch, capsys) -> None:
    from frais.cli import plugins_list

    monkeypatch.setattr("frais.store.plugin_store.init_plugins_config", lambda: None)
    monkeypatch.setattr("frais.store.plugin_store.load_plugins_config", lambda: {"homebrew": False})
    monkeypatch.setattr("frais.plugins.registry.all_plugins", lambda: {
        "applications": _fake_plugin("applications", True),
        "homebrew": _fake_plugin("homebrew", True),
        "npm": _fake_plugin("npm", True, available=False),
    })

    plugins_list(json_output=True)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is True
    names = [p["name"] for p in data["plugins"]]
    assert "applications" in names
    assert "homebrew" in names
    homebrew = next(p for p in data["plugins"] if p["name"] == "homebrew")
    assert homebrew["effective"] == "disabled"


def test_ignore_list_json_output(monkeypatch, capsys) -> None:
    from frais.cli import ignore_list

    monkeypatch.setattr("frais.commands.ignore.init_ignored", lambda: None)
    monkeypatch.setattr("frais.commands.ignore.load_ignored", lambda: {"com.app1", "com.app2"})

    ignore_list(json_output=True)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is True
    assert sorted(data["ignored"]) == ["com.app1", "com.app2"]
    assert data["count"] == 2


def test_ignore_list_json_empty(monkeypatch, capsys) -> None:
    from frais.cli import ignore_list

    monkeypatch.setattr("frais.commands.ignore.init_ignored", lambda: None)
    monkeypatch.setattr("frais.commands.ignore.load_ignored", lambda: set())

    ignore_list(json_output=True)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is True
    assert data["ignored"] == []
    assert data["count"] == 0


def test_ignore_add_json_new(monkeypatch, capsys) -> None:
    from frais.cli import ignore_add

    monkeypatch.setattr("frais.commands.ignore.init_ignored", lambda: None)
    monkeypatch.setattr("frais.commands.ignore.add_ignored", lambda app_id: True)

    ignore_add("com.newapp", json_output=True)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is True
    assert data["app_id"] == "com.newapp"
    assert data["action"] == "added"


def test_ignore_add_json_already_exists(monkeypatch, capsys) -> None:
    from frais.cli import ignore_add

    monkeypatch.setattr("frais.commands.ignore.init_ignored", lambda: None)
    monkeypatch.setattr("frais.commands.ignore.add_ignored", lambda app_id: False)

    ignore_add("com.existing", json_output=True)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is True
    assert data["app_id"] == "com.existing"
    assert data["action"] == "already_ignored"


def test_ignore_remove_json_removes(monkeypatch, capsys) -> None:
    from frais.cli import ignore_remove

    monkeypatch.setattr("frais.commands.ignore.init_ignored", lambda: None)
    monkeypatch.setattr("frais.commands.ignore.remove_ignored", lambda app_id: True)

    ignore_remove("com.remove_me", json_output=True)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is True
    assert data["app_id"] == "com.remove_me"
    assert data["action"] == "removed"


def test_ignore_remove_json_not_in_list(monkeypatch, capsys) -> None:
    from frais.cli import ignore_remove

    monkeypatch.setattr("frais.commands.ignore.init_ignored", lambda: None)
    monkeypatch.setattr("frais.commands.ignore.remove_ignored", lambda app_id: False)

    ignore_remove("com.not_there", json_output=True)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is True
    assert data["app_id"] == "com.not_there"
    assert data["action"] == "not_in_list"


def test_plugins_enable_json(monkeypatch, capsys) -> None:
    from frais.cli import plugins_enable

    monkeypatch.setattr("frais.store.plugin_store.init_plugins_config", lambda: None)
    monkeypatch.setattr("frais.store.plugin_store.save_plugin_state", lambda name, enabled: None)
    monkeypatch.setattr("frais.plugins.registry.all_plugins", lambda: {"homebrew": _fake_plugin("homebrew", True)})

    plugins_enable("homebrew", json_output=True)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is True
    assert data["plugin"] == "homebrew"
    assert data["action"] == "enabled"


def test_plugins_enable_json_unknown(monkeypatch, capsys) -> None:
    from frais.cli import plugins_enable

    monkeypatch.setattr("frais.store.plugin_store.init_plugins_config", lambda: None)
    monkeypatch.setattr("frais.plugins.registry.all_plugins", lambda: {})

    with pytest.raises(typer.Exit) as exc_info:
        plugins_enable("nonexistent", json_output=True)
    assert exc_info.value.exit_code == 1
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is False
    assert "Unknown plugin" in data["error"]


def test_plugins_disable_json(monkeypatch, capsys) -> None:
    from frais.cli import plugins_disable

    monkeypatch.setattr("frais.store.plugin_store.init_plugins_config", lambda: None)
    monkeypatch.setattr("frais.store.plugin_store.save_plugin_state", lambda name, enabled: None)
    monkeypatch.setattr("frais.plugins.registry.all_plugins", lambda: {"homebrew": _fake_plugin("homebrew", True)})

    plugins_disable("homebrew", json_output=True)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is True
    assert data["plugin"] == "homebrew"
    assert data["action"] == "disabled"


def test_plugins_disable_json_unknown(monkeypatch, capsys) -> None:
    from frais.cli import plugins_disable

    monkeypatch.setattr("frais.store.plugin_store.init_plugins_config", lambda: None)
    monkeypatch.setattr("frais.plugins.registry.all_plugins", lambda: {})

    with pytest.raises(typer.Exit) as exc_info:
        plugins_disable("nonexistent", json_output=True)
    assert exc_info.value.exit_code == 1
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is False
    assert "Unknown plugin" in data["error"]


def test_summarize_json_no_cache(monkeypatch, capsys, tmp_path: Path) -> None:
    from frais.cli import _ADVICE_CACHE
    from frais.commands.summarize import summarize

    cache = tmp_path / "nonexistent.json"
    monkeypatch.setattr("frais.cli._ADVICE_CACHE", cache)
    # Restore after test
    try:
        with pytest.raises(typer.Exit) as exc_info:
            summarize("some-id", json_output=True)
        assert exc_info.value.exit_code == 1
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is False
        assert "No scan cache" in data["error"]
    finally:
        monkeypatch.setattr("frais.cli._ADVICE_CACHE", _ADVICE_CACHE)


def test_summarize_json_candidate_not_found(monkeypatch, capsys, tmp_path: Path) -> None:
    from frais.cli import _ADVICE_CACHE
    from frais.commands.summarize import summarize

    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps({"plugin_results": {"applications": {"candidates": []}}}))
    monkeypatch.setattr("frais.cli._ADVICE_CACHE", cache)
    try:
        with pytest.raises(typer.Exit) as exc_info:
            summarize("missing-id", json_output=True)
        assert exc_info.value.exit_code == 1
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is False
        assert "No candidate found" in data["error"]
    finally:
        monkeypatch.setattr("frais.cli._ADVICE_CACHE", _ADVICE_CACHE)


def test_scan_json_bad_plugins(monkeypatch, capsys) -> None:
    from frais.commands.scan import scan

    from frais.models import SystemProfile
    monkeypatch.setattr("frais.system.detect_system", lambda: SystemProfile(
        os_name="macOS", os_version="15.0", arch="arm64", applications_paths=["/Applications"],
    ))
    monkeypatch.setattr("frais.coordinator.select_plugins", lambda explicit=None: {})
    monkeypatch.setattr("frais.commands.scan._split_plugins", lambda x: ["badone"])

    with pytest.raises(typer.Exit) as exc_info:
        scan(plugins="badone", json_output=True)
    assert exc_info.value.exit_code == 1
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is False
    assert "badone" in data["error"]


def test_config_test_json_no_config(monkeypatch, capsys) -> None:
    from frais.commands.config import config_test

    monkeypatch.setattr("frais.commands.config.require_config",
                        lambda: (_ for _ in ()).throw(ValueError("No LLM provider configured")))

    with pytest.raises(typer.Exit) as exc_info:
        config_test(json_output=True)
    assert exc_info.value.exit_code == 2
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is False
    assert data["reason"] == "config_missing"
    assert "No LLM provider" in data["error"]
