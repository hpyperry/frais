from __future__ import annotations

import json
import subprocess

from checkupgrade.plugins.homebrew import HomebrewPlugin
from checkupgrade.system import detect_system


def test_homebrew_formula_candidate(monkeypatch) -> None:
    def fake_which(name: str) -> str | None:
        return "/opt/homebrew/bin/brew" if name == "brew" else None

    def fake_run(command, check=False, capture_output=True, text=True, timeout=60):
        joined = " ".join(command)
        if "outdated" in joined:
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps(
                    {
                        "formulae": [
                            {
                                "name": "node",
                                "installed_versions": ["24.1.0"],
                                "current_version": "24.2.0",
                            }
                        ],
                        "casks": [],
                    }
                ),
                "",
            )
        if "info" in joined:
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps(
                    {
                        "formulae": [
                            {
                                "name": "node",
                                "homepage": "https://nodejs.org",
                                "dependencies": ["openssl@3"],
                            }
                        ]
                    }
                ),
                "",
            )
        if "uses" in joined:
            return subprocess.CompletedProcess(command, 0, "yarn\npnpm\n", "")
        raise AssertionError(command)

    monkeypatch.setattr("checkupgrade.plugins.homebrew.shutil.which", fake_which)
    monkeypatch.setattr("checkupgrade.plugins.homebrew.subprocess.run", fake_run)

    candidates, skipped = HomebrewPlugin().scan(detect_system())

    assert skipped == []
    assert candidates[0].item.name == "node"
    assert candidates[0].latest_version == "24.2.0"
    assert candidates[0].command == ["brew", "upgrade", "node"]
    assert candidates[0].dependency_impact.used_by == ["pnpm", "yarn"]
