from __future__ import annotations

import json
import subprocess

from checkupgrade.models import SourceKind
from checkupgrade.plugins.npm import NpmPlugin
from checkupgrade.system import detect_system


def test_npm_outdated_candidate(monkeypatch) -> None:
    def fake_which(name: str) -> str | None:
        return "/usr/local/bin/npm" if name == "npm" else None

    def fake_run(command, check=False, capture_output=True, text=True, timeout=60):
        return subprocess.CompletedProcess(
            command,
            1,
            json.dumps({
                "typescript": {
                    "current": "5.7.0",
                    "wanted": "5.8.0",
                    "latest": "5.8.0",
                    "dependent": "global",
                    "location": "/usr/local/lib/node_modules/typescript",
                },
            }),
            "",
        )

    monkeypatch.setattr("checkupgrade.plugins.npm.shutil.which", fake_which)
    monkeypatch.setattr("checkupgrade.plugins.npm.subprocess.run", fake_run)

    result = NpmPlugin().scan(detect_system())

    assert result.skipped == []
    assert len(result.candidates) == 1
    c = result.candidates[0]
    assert c.item.name == "typescript"
    assert c.item.id == "npm:typescript"
    assert c.item.source == SourceKind.NPM_GLOBAL
    assert c.item.current_version == "5.7.0"
    assert c.latest_version == "5.8.0"
    assert c.can_auto_update is True
    assert c.command == ["npm", "install", "-g", "typescript"]


def test_npm_no_outdated(monkeypatch) -> None:
    def fake_which(name: str) -> str | None:
        return "/usr/local/bin/npm" if name == "npm" else None

    def fake_run(command, check=False, capture_output=True, text=True, timeout=60):
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("checkupgrade.plugins.npm.shutil.which", fake_which)
    monkeypatch.setattr("checkupgrade.plugins.npm.subprocess.run", fake_run)

    result = NpmPlugin().scan(detect_system())

    assert result.candidates == []
    assert result.skipped == []


def test_npm_unavailable(monkeypatch) -> None:
    monkeypatch.setattr("checkupgrade.plugins.npm.shutil.which", lambda name: None)

    result = NpmPlugin().scan(detect_system())

    assert result.candidates == []
    assert len(result.skipped) == 1
    assert "npm is not installed" in result.skipped[0]


def test_npm_multiple_packages(monkeypatch) -> None:
    def fake_which(name: str) -> str | None:
        return "/usr/local/bin/npm" if name == "npm" else None

    def fake_run(command, check=False, capture_output=True, text=True, timeout=60):
        return subprocess.CompletedProcess(
            command,
            1,
            json.dumps({
                "typescript": {
                    "current": "5.7.0",
                    "wanted": "5.8.0",
                    "latest": "5.8.0",
                    "dependent": "global",
                    "location": "/usr/local/lib/node_modules/typescript",
                },
                "pnpm": {
                    "current": "9.0.0",
                    "wanted": "9.1.0",
                    "latest": "10.0.0",
                    "dependent": "global",
                    "location": "/usr/local/lib/node_modules/pnpm",
                },
            }),
            "",
        )

    monkeypatch.setattr("checkupgrade.plugins.npm.shutil.which", fake_which)
    monkeypatch.setattr("checkupgrade.plugins.npm.subprocess.run", fake_run)

    result = NpmPlugin().scan(detect_system())

    assert result.skipped == []
    assert len(result.candidates) == 2
    names = {c.item.name for c in result.candidates}
    assert names == {"typescript", "pnpm"}
    # pnpm should use "latest" (10.0.0) over "wanted" (9.1.0)
    pnpm = next(c for c in result.candidates if c.item.name == "pnpm")
    assert pnpm.latest_version == "10.0.0"
