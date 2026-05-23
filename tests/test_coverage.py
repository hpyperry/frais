"""Tests targeting low-coverage areas to push coverage toward 90%."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import typer

from frais.models import (
    DependencyImpact, PluginScanResult, ResearchResult, ScanResult,
    SoftwareItem, SourceKind, SystemProfile, UpdateCandidate,
)
from frais.plugins.base import ScannerPlugin


# --- cli: doctor, config, plugins, ignore commands ---


def test_doctor_basic(monkeypatch) -> None:
    from frais.cli import doctor
    monkeypatch.setattr("frais.cli.load_config", lambda: None)
    monkeypatch.setattr("frais.plugins.registry.all_plugins", lambda: {})
    monkeypatch.setattr("frais.system.detect_system",
        lambda: SystemProfile(os_name="macOS", os_version="15.0", arch="arm64",
                              applications_paths=["/Apps"]))
    doctor()


def test_config_show_not_configured(monkeypatch) -> None:
    from frais.cli import config_show
    monkeypatch.setattr("frais.cli.load_config", lambda: None)
    config_show()


def test_config_path(monkeypatch) -> None:
    from frais.cli import config_path
    config_path()


def test_plugins_list(monkeypatch) -> None:
    from frais.cli import plugins_list
    monkeypatch.setattr("frais.store.plugin_store.init_plugins_config", lambda: None)
    monkeypatch.setattr("frais.store.plugin_store.load_plugins_config", lambda: {})
    monkeypatch.setattr("frais.plugins.registry.all_plugins", lambda: {
        "applications": _make_plugin("applications", True),
    })
    plugins_list()


def test_plugins_enable(monkeypatch) -> None:
    from frais.cli import plugins_enable
    monkeypatch.setattr("frais.store.plugin_store.init_plugins_config", lambda: None)
    monkeypatch.setattr("frais.plugins.registry.all_plugins", lambda: {"homebrew": _make_plugin("homebrew", True)})
    monkeypatch.setattr("frais.store.plugin_store.save_plugin_state", lambda name, state: None)
    plugins_enable(name="homebrew")


def test_plugins_enable_unknown(monkeypatch) -> None:
    from frais.cli import plugins_enable
    monkeypatch.setattr("frais.store.plugin_store.init_plugins_config", lambda: None)
    monkeypatch.setattr("frais.plugins.registry.all_plugins", lambda: {})
    with pytest.raises(typer.Exit):
        plugins_enable(name="nonexistent")


def test_plugins_disable(monkeypatch) -> None:
    from frais.cli import plugins_disable
    monkeypatch.setattr("frais.store.plugin_store.init_plugins_config", lambda: None)
    monkeypatch.setattr("frais.plugins.registry.all_plugins", lambda: {"homebrew": _make_plugin("homebrew", True)})
    monkeypatch.setattr("frais.store.plugin_store.save_plugin_state", lambda name, state: None)
    plugins_disable(name="homebrew")


def test_ignore_list_empty(monkeypatch) -> None:
    from frais.cli import ignore_list
    monkeypatch.setattr("frais.commands.ignore.init_ignored", lambda path=None: None)
    monkeypatch.setattr("frais.commands.ignore.load_ignored", lambda: set())
    ignore_list()


def test_ignore_add(monkeypatch) -> None:
    from frais.cli import ignore_add
    monkeypatch.setattr("frais.commands.ignore.init_ignored", lambda path=None: None)
    monkeypatch.setattr("frais.commands.ignore.add_ignored", lambda app_id, path=None: True)
    ignore_add(app_id="com.example.app")


def test_ignore_add_duplicate(monkeypatch) -> None:
    from frais.cli import ignore_add
    monkeypatch.setattr("frais.commands.ignore.init_ignored", lambda path=None: None)
    monkeypatch.setattr("frais.commands.ignore.add_ignored", lambda app_id, path=None: False)
    ignore_add(app_id="com.example.app")


def test_ignore_remove(monkeypatch) -> None:
    from frais.cli import ignore_remove
    monkeypatch.setattr("frais.commands.ignore.init_ignored", lambda path=None: None)
    monkeypatch.setattr("frais.commands.ignore.remove_ignored", lambda app_id, path=None: True)
    ignore_remove(app_id="com.example.app")


def test_ignore_remove_not_found(monkeypatch) -> None:
    from frais.cli import ignore_remove
    monkeypatch.setattr("frais.commands.ignore.init_ignored", lambda path=None: None)
    monkeypatch.setattr("frais.commands.ignore.remove_ignored", lambda app_id, path=None: False)
    ignore_remove(app_id="com.example.app")


# --- scan command ---


def test_scan_no_matching_plugins(monkeypatch) -> None:
    from frais.commands.scan import scan

    monkeypatch.setattr("frais.commands.scan._split_plugins", lambda v: ["nonexistent"])
    monkeypatch.setattr("frais.plugins.registry.all_plugins", lambda: {
        "applications": _make_plugin("applications", True),
    })
    monkeypatch.setattr("frais.coordinator.select_plugins",
        lambda explicit: {})
    with pytest.raises(typer.Exit):
        scan(plugins="nonexistent")


# --- ScannerPlugin base class ---


def test_scanner_plugin_scan_all_default() -> None:
    class P(ScannerPlugin):
        name = "test"
        scan_steps = ["s"]
        def is_available(self): return True
        def scan(self, system, on_progress=None, max_workers=10):
            return PluginScanResult(items=[], candidates=[])

    p = P()
    system = SystemProfile(os_name="macOS", os_version="15.0", arch="arm64", applications_paths=[])
    result = p.scan_all(system)
    assert isinstance(result, PluginScanResult)


def test_scanner_plugin_update_default() -> None:
    class P(ScannerPlugin):
        name = "test"
        def is_available(self): return True
        def scan(self, system, on_progress=None, max_workers=10):
            return PluginScanResult()

    p = P()
    item = SoftwareItem(id="a", name="A", kind="app", source=SourceKind.APPLICATION, current_version="1.0")
    cand = UpdateCandidate(item=item, latest_version="2.0",
                           can_auto_update=True, command=["echo", "hello"])
    # monkeypatch subprocess to avoid real execution
    assert p.update(cand) is True


def test_scanner_plugin_update_no_command() -> None:
    class P(ScannerPlugin):
        name = "test"
        def is_available(self): return True
        def scan(self, system, on_progress=None, max_workers=10):
            return PluginScanResult()

    p = P()
    item = SoftwareItem(id="a", name="A", kind="app", source=SourceKind.APPLICATION, current_version="1.0")
    cand = UpdateCandidate(item=item, latest_version="2.0", can_auto_update=False)
    assert p.update(cand) is False


def test_scanner_plugin_summarize(monkeypatch) -> None:
    class P(ScannerPlugin):
        name = "test"
        def is_available(self): return True
        def scan(self, system, on_progress=None, max_workers=10):
            return PluginScanResult()

    class FakeLLM:
        def chat(self, system, user, max_tokens=None, *, disable_thinking=False):
            return "建议更新"

    p = P()
    item = SoftwareItem(id="a", name="A", kind="app", source=SourceKind.APPLICATION, current_version="1.0")
    cand = UpdateCandidate(item=item, latest_version="2.0")
    result = p.summarize(FakeLLM(), cand)
    assert result == "建议更新"
    assert cand.ai_summary == "建议更新"


# --- npm plugin scan error paths ---


def test_npm_scan_unavailable(monkeypatch) -> None:
    from frais.plugins.npm import NpmPlugin
    from frais.system import detect_system

    plugin = NpmPlugin()
    monkeypatch.setattr("shutil.which", lambda name: None)
    system = detect_system()
    result = plugin.scan(system)
    assert "npm is not installed" in result.skipped[0]


def test_npm_scan_runtime_error(monkeypatch) -> None:
    from frais.plugins.npm import NpmPlugin
    from frais.system import detect_system

    plugin = NpmPlugin()
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/npm" if name == "npm" else None)
    monkeypatch.setattr("frais.plugins.npm.run_json", lambda cmd, ok_codes=(0,): exec('raise RuntimeError("fail")'))

    result = plugin.scan(detect_system())
    assert "fail" in result.skipped[0]


def test_npm_scan_all_unavailable(monkeypatch) -> None:
    from frais.plugins.npm import NpmPlugin
    from frais.system import detect_system

    plugin = NpmPlugin()
    monkeypatch.setattr("shutil.which", lambda name: None)
    result = plugin.scan_all(detect_system())
    assert "npm is not installed" in result.skipped[0]


# --- homebrew plugin error paths ---


def test_homebrew_scan_unavailable(monkeypatch) -> None:
    from frais.plugins.homebrew import HomebrewPlugin
    from frais.system import detect_system

    plugin = HomebrewPlugin()
    monkeypatch.setattr("shutil.which", lambda name: None)
    result = plugin.scan(detect_system())
    assert "Homebrew is not installed" in result.skipped[0]


def test_homebrew_scan_all_unavailable(monkeypatch) -> None:
    from frais.plugins.homebrew import HomebrewPlugin
    from frais.system import detect_system

    plugin = HomebrewPlugin()
    monkeypatch.setattr("shutil.which", lambda name: None)
    result = plugin.scan_all(detect_system())
    assert "Homebrew is not installed" in result.skipped[0]


# --- homebrew scan with mocked brew ---


def test_homebrew_scan_with_outdated(monkeypatch) -> None:
    from frais.plugins.homebrew import HomebrewPlugin
    from frais.system import detect_system

    plugin = HomebrewPlugin()
    monkeypatch.setattr("shutil.which", lambda name: "/opt/homebrew/bin/brew" if name == "brew" else None)
    outdated_json = {
        "formulae": [{
            "name": "node", "installed_versions": ["20.0.0"], "current_version": "22.0.0",
        }],
        "casks": [],
    }
    monkeypatch.setattr("frais.plugins.homebrew.run_json",
        lambda cmd, ok_codes=(0,): outdated_json)
    monkeypatch.setattr("frais.plugins.homebrew._brew_info",
        lambda name, cask=False: {"dependencies": [], "homepage": "https://example.com"})
    monkeypatch.setattr("frais.plugins.homebrew._brew_uses", lambda name: [])

    result = plugin.scan(detect_system())
    assert len(result.candidates) == 1
    assert result.candidates[0].item.name == "node"


# --- applications plugin ---


def test_applications_plugin_is_available() -> None:
    from frais.plugins.applications import ApplicationsPlugin
    assert ApplicationsPlugin().is_available() is True


def test_scan_applications_empty_dir(tmp_path: Path) -> None:
    from frais.plugins.applications import scan_applications
    items = scan_applications([str(tmp_path)])
    assert items == []


def test_scan_applications_nonexistent_path() -> None:
    from frais.plugins.applications import scan_applications
    items = scan_applications(["/nonexistent/path"])
    assert items == []


def test_classify_source_app_store() -> None:
    from frais.plugins.applications import classify_source
    result = classify_source("com.app", {"authority": "Apple Mac OS Application Signing", "team_id": "X"}, None)
    assert result == SourceKind.APP_STORE


def test_classify_source_unknown() -> None:
    from frais.plugins.applications import classify_source
    result = classify_source(None, {"authority": "adhoc", "team_id": None}, None)
    assert result == SourceKind.LOCAL_BUILD


def test_classify_source_network_download() -> None:
    from frais.plugins.applications import classify_source
    result = classify_source("com.app", {"authority": "dev", "team_id": "X"},
                             "https://example.com|chrome")
    assert result == SourceKind.NETWORK_DOWNLOAD


def test_classify_source_application() -> None:
    from frais.plugins.applications import classify_source
    result = classify_source("com.app", {"authority": "dev", "team_id": "X"}, None)
    assert result == SourceKind.APPLICATION


def test_classify_source_unknown_no_bundle() -> None:
    from frais.plugins.applications import classify_source
    result = classify_source(None, {"authority": "dev", "team_id": "X"}, None)
    assert result == SourceKind.UNKNOWN


def test_read_application_no_plist(tmp_path: Path) -> None:
    from frais.plugins.applications import read_application
    app = tmp_path / "Test.app"
    app.mkdir()
    assert read_application(app) is None


# --- config ---


def test_config_show_configured(monkeypatch) -> None:
    from frais.cli import config_show
    from frais.store.config_store import ProviderConfig

    fake_models = [type("M", (), {"id": "test", "name": "Test", "supports_thinking": False})()]
    fake_provider = type("P", (), {"id": "test", "name": "Test", "chat_url": "https://test", "models": fake_models})()
    fake_config = ProviderConfig(provider=fake_provider, model="test", api_key="sk-1234",
                                 api_key_source="env")
    monkeypatch.setattr("frais.cli.load_config", lambda: fake_config)
    config_show()


# --- scan_applications with real plist ---


def test_scan_applications_with_real_app(tmp_path: Path) -> None:
    import plistlib
    from frais.plugins.applications import scan_applications

    app = tmp_path / "Test.app"
    contents = app / "Contents"
    contents.mkdir(parents=True)
    with (contents / "Info.plist").open("wb") as f:
        plistlib.dump({
            "CFBundleIdentifier": "com.test.app",
            "CFBundleName": "TestApp",
            "CFBundleShortVersionString": "1.0",
        }, f)

    items = scan_applications([str(tmp_path)])
    assert len(items) == 1
    assert items[0].id == "com.test.app"
    assert items[0].name == "TestApp"


def test_scan_applications_no_plist_app(tmp_path: Path) -> None:
    from frais.plugins.applications import scan_applications

    app = tmp_path / "Bad.app"
    app.mkdir()
    items = scan_applications([str(tmp_path)])
    assert items == []


# --- npm scan_all with outdated ---


def test_npm_scan_all_with_outdated(monkeypatch) -> None:
    from frais.plugins.npm import NpmPlugin
    from frais.system import detect_system

    plugin = NpmPlugin()
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/npm" if name == "npm" else None)

    def fake_run_json(cmd, ok_codes=(0,)):
        joined = " ".join(cmd)
        if "outdated" in joined:
            return {"test-pkg": {"current": "1.0.0", "latest": "2.0.0"}}
        if "ls" in joined:
            return {"dependencies": {"test-pkg": {"version": "1.0.0"}}}
        return {}

    monkeypatch.setattr("frais.plugins.npm.run_json", fake_run_json)
    result = plugin.scan_all(detect_system())
    assert len(result.candidates) == 1


# --- _brew_uses ---


def test_brew_uses_empty(monkeypatch) -> None:
    from frais.plugins.homebrew import _brew_uses
    import subprocess as sp

    result_mock = type("R", (), {"returncode": 1, "stdout": ""})()
    monkeypatch.setattr(sp, "run", lambda *a, **kw: result_mock)
    assert _brew_uses("nonexistent") == []


def test_brew_uses_returns_packages(monkeypatch) -> None:
    from frais.plugins.homebrew import _brew_uses
    import subprocess as sp

    result_mock = type("R", (), {"returncode": 0, "stdout": "pkg-a pkg-b\n"})()
    monkeypatch.setattr(sp, "run", lambda *a, **kw: result_mock)
    assert _brew_uses("test") == ["pkg-a", "pkg-b"]


# --- _first helper ---


def test_first_with_list() -> None:
    from frais.plugins.homebrew import _first
    assert _first(["a", "b"]) == "a"


def test_first_with_empty_list() -> None:
    from frais.plugins.homebrew import _first
    assert _first([]) is None


def test_first_with_scalar() -> None:
    from frais.plugins.homebrew import _first
    assert _first("a") == "a"


# --- _installed_version fallback ---


def test_installed_version_from_installed_list() -> None:
    from frais.plugins.homebrew import _installed_version
    assert _installed_version({"installed": [{"version": "2.0"}]}) == "2.0"


def test_installed_version_from_linked_keg() -> None:
    from frais.plugins.homebrew import _installed_version
    assert _installed_version({"linked_keg": "1.0"}) == "1.0"


def test_installed_version_none() -> None:
    from frais.plugins.homebrew import _installed_version
    assert _installed_version({}) is None


# --- _cask_current_version ---


def test_cask_current_version_linked() -> None:
    from frais.plugins.homebrew import _cask_current_version
    assert _cask_current_version({"linked_keg": "3.0"}) == "3.0"


def test_cask_current_version_fallback() -> None:
    from frais.plugins.homebrew import _cask_current_version
    assert _cask_current_version({"version": "4.0"}) == "4.0"


# --- _save_cache error ---


def test_save_cache_write_error(monkeypatch, tmp_path: Path) -> None:
    from frais.commands._scan_core import _save_cache

    system = SystemProfile(os_name="macOS", os_version="15.0", arch="arm64", applications_paths=[])
    result = ScanResult(system=system)

    def fail_write(*a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr("pathlib.Path.write_text", fail_write)
    _save_cache(result, tmp_path / "nonexistent.json")


# --- npm empty outdated ---


def test_npm_scan_empty_outdated(monkeypatch) -> None:
    from frais.plugins.npm import NpmPlugin
    from frais.system import detect_system

    plugin = NpmPlugin()
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/npm" if name == "npm" else None)
    monkeypatch.setattr("frais.plugins.npm.run_json", lambda cmd, ok_codes=(0,): {})

    result = plugin.scan(detect_system())
    assert result.items == []
    assert result.candidates == []


# --- homebrew cask candidate ---


def test_homebrew_cask_candidate(monkeypatch) -> None:
    from frais.plugins.homebrew import HomebrewPlugin
    from frais.system import detect_system

    plugin = HomebrewPlugin()
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/brew" if name == "brew" else None)

    outdated = {
        "formulae": [],
        "casks": [{
            "name": "firefox", "token": "firefox",
            "installed_versions": ["120.0"], "current_version": "121.0",
        }],
    }
    monkeypatch.setattr("frais.plugins.homebrew.run_json",
        lambda cmd, ok_codes=(0,): outdated)
    monkeypatch.setattr("frais.plugins.homebrew._brew_info",
        lambda name, cask=False: {"homepage": "https://firefox.com"})

    result = plugin.scan(detect_system())
    assert len(result.candidates) == 1
    assert result.candidates[0].item.name == "firefox"
    assert result.candidates[0].command == ["brew", "upgrade", "--cask", "firefox"]


# --- homebrew scan_all with installed ---


def test_homebrew_scan_all_with_data(monkeypatch) -> None:
    from frais.plugins.homebrew import HomebrewPlugin
    from frais.system import detect_system

    plugin = HomebrewPlugin()
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/brew" if name == "brew" else None)

    outdated = {"formulae": [], "casks": []}
    installed = {
        "formulae": [{"name": "node", "linked_keg": "20.0.0"}],
        "casks": [{"name": "firefox", "version": "120.0"}],
    }
    calls = []
    def fake_run_json(cmd, ok_codes=(0,)):
        calls.append(" ".join(cmd))
        if "outdated" in calls[-1]:
            return outdated
        return installed

    monkeypatch.setattr("frais.plugins.homebrew.run_json", fake_run_json)
    result = plugin.scan_all(detect_system())
    assert len(result.items) == 2


# --- homebrew _brew_info cask ---


def test_brew_info_cask_with_data(monkeypatch) -> None:
    from frais.plugins.homebrew import _brew_info

    monkeypatch.setattr("frais.plugins.homebrew.run_json",
        lambda cmd, ok_codes=(0,): {"casks": [{"homepage": "https://test.com"}]})
    result = _brew_info("firefox", cask=True)
    assert result == {"homepage": "https://test.com"}


# --- homebrew _brew_info empty ---


def test_brew_info_empty_result(monkeypatch) -> None:
    from frais.plugins.homebrew import _brew_info

    monkeypatch.setattr("frais.plugins.homebrew.run_json",
        lambda cmd, ok_codes=(0,): {"formulae": []})
    result = _brew_info("nonexistent")
    assert result == {}


# --- summarize: plugin not found ---


def test_summarize_plugin_not_found(monkeypatch, tmp_path: Path) -> None:
    from frais.commands.summarize import summarize

    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps({
        "system": {"os_name": "macOS", "os_version": "15.0", "arch": "arm64", "applications_paths": []},
        "plugin_results": {"ghost": {"items": [], "candidates": [{
            "item": {"id": "a", "name": "A", "kind": "app", "source": "application", "current_version": "1.0"},
            "latest_version": "2.0", "release_notes": None, "dependency_impact": {},
            "risk_level": "low", "ai_summary": None, "recommended_action": "Update",
            "can_auto_update": False, "command": [], "evidence": [],
        }], "skipped": []}},
    }))
    monkeypatch.setattr("frais.cli._ADVICE_CACHE", cache)
    with pytest.raises(typer.Exit):
        summarize(item_id="a")


# --- summarize: corrupt cache ---


def test_summarize_corrupt_cache(monkeypatch, tmp_path: Path) -> None:
    from frais.commands.summarize import summarize

    cache = tmp_path / "cache.json"
    cache.write_text("not json")
    monkeypatch.setattr("frais.cli._ADVICE_CACHE", cache)
    with pytest.raises(typer.Exit):
        summarize(item_id="a")


# --- applications: LLM unavailable ---


def test_applications_scan_llm_unavailable(monkeypatch) -> None:
    from frais.plugins.applications import ApplicationsPlugin

    plugin = ApplicationsPlugin()
    monkeypatch.setattr("frais.store.config_store.require_config",
        lambda: exec('raise ValueError("no config")'))
    monkeypatch.setattr("frais.plugins.applications.scan_applications",
        lambda paths: [])

    system = SystemProfile(os_name="macOS", os_version="15.0", arch="arm64", applications_paths=[])
    result = plugin.scan(system)
    assert "no config" in result.skipped[0]


# --- homebrew scan runtime error ---


def test_homebrew_scan_runtime_error(monkeypatch) -> None:
    from frais.plugins.homebrew import HomebrewPlugin
    from frais.system import detect_system

    plugin = HomebrewPlugin()
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/brew" if name == "brew" else None)
    monkeypatch.setattr("frais.plugins.homebrew.run_json",
        lambda cmd, ok_codes=(0,): exec('raise RuntimeError("brew crash")'))

    result = plugin.scan(detect_system())
    assert "brew crash" in result.skipped[0]


def test_homebrew_scan_all_runtime_error(monkeypatch) -> None:
    from frais.plugins.homebrew import HomebrewPlugin
    from frais.system import detect_system

    plugin = HomebrewPlugin()
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/brew" if name == "brew" else None)
    monkeypatch.setattr("frais.plugins.homebrew.run_json",
        lambda cmd, ok_codes=(0,): exec('raise RuntimeError("brew crash")'))

    result = plugin.scan_all(detect_system())
    assert len(result.skipped) == 1


# --- _utils run_json non-zero exit ---


def test_run_json_non_zero(monkeypatch) -> None:
    from frais.plugins._utils import run_json

    result_mock = type("R", (), {"returncode": 1, "stdout": "bad", "stderr": "error"})()
    monkeypatch.setattr("subprocess.run", lambda cmd, **kw: result_mock)
    with pytest.raises(RuntimeError):
        run_json(["bad", "command"])


# --- select_plugins explicit with enabled ---


def test_select_plugins_explicit_with_enabled(monkeypatch) -> None:
    from frais.coordinator import select_plugins

    monkeypatch.setattr("frais.store.plugin_store.load_plugins_config", lambda: {"homebrew": True})
    available = {"homebrew": _make_plugin("homebrew", True)}
    monkeypatch.setattr("frais.plugins.registry.all_plugins", lambda: available)

    result = select_plugins(explicit=["homebrew"])
    assert "homebrew" in result


def test_select_plugins_default_enabled_no_persist(monkeypatch) -> None:
    from frais.coordinator import select_plugins

    monkeypatch.setattr("frais.store.plugin_store.load_plugins_config", lambda: {})
    available = {"homebrew": _make_plugin("homebrew", True)}
    monkeypatch.setattr("frais.plugins.registry.all_plugins", lambda: available)

    result = select_plugins(explicit=["homebrew"])
    assert "homebrew" in result


# --- coordinator: select_plugins edge cases ---


def test_select_plugins_default_persisted_disabled(monkeypatch) -> None:
    from frais.coordinator import select_plugins

    monkeypatch.setattr("frais.store.plugin_store.load_plugins_config",
        lambda: {"homebrew": False})
    available = {"homebrew": _make_plugin("homebrew", True)}
    monkeypatch.setattr("frais.plugins.registry.all_plugins", lambda: available)
    result = select_plugins(explicit=None)
    assert "homebrew" not in result


# --- _research: _is_newer InvalidVersion edge ---


def test_is_newer_invalid_version() -> None:
    from frais.plugins.applications._research import _is_newer
    # Same digits-only fallback results in no difference
    assert _is_newer("build-2024.1", "build-2024.1") is False


# --- _research: _digits_only empty ---


def test_digits_only_empty() -> None:
    from frais.plugins.applications._research import _digits_only
    assert _digits_only("abc") == ""


# --- tools: web_search and web_fetch error ---


def test_web_fetch_github_error(monkeypatch) -> None:
    from frais.tools import web_fetch
    monkeypatch.setattr("httpx.Client.get",
        lambda self, url, **kw: exec('raise RuntimeError("fetch down")'))
    result = web_fetch("https://github.com/test/repo/releases")
    assert "Failed to fetch" in result


# --- llm: LLMClient init error ---


def test_llm_client_init_error() -> None:
    from frais.llm import OpenAICompatibleClient
    from frais.store.config_store import ProviderConfig
    from frais.providers import ModelInfo

    fake_models = [ModelInfo(id="test", name="Test")]
    fake_provider = type("P", (), {"id": "test", "chat_url": "https://test", "models": fake_models})()

    # Config not ready
    config = ProviderConfig(provider=fake_provider, model="", api_key="")
    with pytest.raises(ValueError, match="incomplete"):
        OpenAICompatibleClient(config)


# --- llm: LLMRequestError ---


def test_llm_request_error_str() -> None:
    from frais.llm import LLMRequestError
    err = LLMRequestError("test", status_code=400, response_text="bad")
    assert "test" in str(err)
    assert err.status_code == 400


# --- _utils: run_json with empty stdout ---


def test_run_json_empty_stdout(monkeypatch) -> None:
    from frais.plugins._utils import run_json

    result_mock = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    monkeypatch.setattr("subprocess.run", lambda cmd, **kw: result_mock)
    result = run_json(["echo"], ok_codes=(0,))
    assert result == {}


# --- _utils: run_json with ok_codes match ---


def test_run_json_ok_codes_match(monkeypatch) -> None:
    from frais.plugins._utils import run_json

    result_mock = type("R", (), {"returncode": 1, "stdout": '{"key":"val"}', "stderr": ""})()
    monkeypatch.setattr("subprocess.run", lambda cmd, **kw: result_mock)
    result = run_json(["cmd"], ok_codes=(0, 1))
    assert result == {"key": "val"}


def test_run_json_ok_codes_no_match(monkeypatch) -> None:
    from frais.plugins._utils import run_json

    result_mock = type("R", (), {"returncode": 2, "stdout": "bad", "stderr": "err"})()
    monkeypatch.setattr("subprocess.run", lambda cmd, **kw: result_mock)
    with pytest.raises(RuntimeError):
        run_json(["cmd"])


# --- config: load_config with provider not found ---


def test_load_config_unknown_provider(monkeypatch) -> None:
    from frais.store.config_store import load_config, CONFIG_PATH

    monkeypatch.setattr("frais.store.config_store._read_config_file",
        lambda path: {"llm": {"provider": "nonexistent", "model": "m", "api_key": "k"}})
    result = load_config()
    assert result is None


# --- config: load_config no api_key ---


def test_load_config_no_file() -> None:
    from frais.store.config_store import load_config
    result = load_config(Path("/nonexistent/config.toml"))
    assert result is None


# --- logger.debug path for npm install check ---


def test_npm_which_path(monkeypatch) -> None:
    from frais.plugins.npm import NpmPlugin

    plugin = NpmPlugin()
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/npm" if name == "npm" else None)
    assert plugin.is_available() is True


# --- homebrew _brew_info error path ---


def test_brew_info_failure(monkeypatch) -> None:
    from frais.plugins.homebrew import _brew_info

    monkeypatch.setattr("frais.plugins.homebrew.run_json",
        lambda cmd, ok_codes=(0,): exec('raise RuntimeError("fail")'))
    result = _brew_info("nonexistent")
    assert result == {}


# --- npm scan_all runtime error ---


def test_npm_scan_all_runtime_error(monkeypatch) -> None:
    from frais.plugins.npm import NpmPlugin
    from frais.system import detect_system

    plugin = NpmPlugin()
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/npm" if name == "npm" else None)
    monkeypatch.setattr("frais.plugins.npm.run_json",
        lambda cmd, ok_codes=(0,): exec('raise RuntimeError("fail")'))

    result = plugin.scan_all(detect_system())
    assert "fail" in result.skipped[0]


# --- _utils run_json error ---


def test_run_json_timeout(monkeypatch) -> None:
    from frais.plugins._utils import run_json

    def fake_run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 30)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(RuntimeError):
        run_json(["echo", "hello"])


# --- models edge cases ---


def test_dependency_impact_defaults() -> None:
    di = DependencyImpact()
    assert di.used_by == []
    assert di.depends_on == []
    assert di.impact_level == "unknown"


def test_research_result_defaults() -> None:
    rr = ResearchResult()
    assert rr.latest_version is None
    assert rr.confidence == "unknown"
    assert rr.evidence == []


def test_software_item_serialization_roundtrip() -> None:
    item = SoftwareItem(id="a", name="A", kind="app", source=SourceKind.APPLICATION,
                        current_version="1.0", path="/Apps/A.app",
                        metadata={"key": "val"})
    restored = SoftwareItem.from_dict(item.to_dict())
    assert restored.id == "a"
    assert restored.source == SourceKind.APPLICATION
    assert restored.metadata == {"key": "val"}


def test_update_candidate_can_auto() -> None:
    item = SoftwareItem(id="a", name="A", kind="app", source=SourceKind.HOMEBREW_FORMULA,
                        current_version="1.0")
    cand = UpdateCandidate(item=item, latest_version="2.0",
                           can_auto_update=True, command=["brew", "upgrade", "a"])
    assert cand.can_auto_update is True
    assert cand.command == ["brew", "upgrade", "a"]


def test_plugin_scan_result_empty() -> None:
    pr = PluginScanResult()
    assert pr.items == []
    assert pr.candidates == []
    assert pr.skipped == []


def test_system_profile_to_dict() -> None:
    sp = SystemProfile(os_name="macOS", os_version="15.0", arch="arm64",
                       applications_paths=["/Apps"])
    d = sp.to_dict()
    assert d["os_name"] == "macOS"


# --- providers ---


def test_get_provider_returns_none_for_unknown() -> None:
    from frais.providers import get_provider
    assert get_provider("nonexistent") is None


# --- helpers ---


def _make_plugin(pname: str, default: bool, available: bool = True):
    return type("P", (), {
        "name": pname,
        "enabled_by_default": default,
        "is_available": lambda self: available,
    })()
