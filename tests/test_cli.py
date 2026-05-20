from __future__ import annotations

from checkupgrade.cli import run_scan


def test_explicit_plugins_skip_applications(monkeypatch) -> None:
    called = False

    def fake_scan_applications(paths):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr("checkupgrade.cli.scan_applications", fake_scan_applications)
    monkeypatch.setattr("checkupgrade.cli.enabled_plugins", lambda names: [])

    result = run_scan(plugin_names=["homebrew"])

    assert result.applications == []
    assert not called
