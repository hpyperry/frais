from __future__ import annotations

import json
import subprocess

from mise.plugins.homebrew import HomebrewPlugin
from mise.system import detect_system


def test_homebrew_formula_candidate(monkeypatch) -> None:
    def fake_which(name: str) -> str | None:
        return "/opt/homebrew/bin/brew" if name == "brew" else None

    def fake_run(command, check=False, capture_output=True, text=True, timeout=60, env=None):
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

    monkeypatch.setattr("mise.plugins.homebrew.shutil.which", fake_which)
    monkeypatch.setattr("mise.plugins._utils.subprocess.run", fake_run)

    result = HomebrewPlugin().scan(detect_system())

    assert result.skipped == []
    assert result.candidates[0].item.name == "node"
    assert result.candidates[0].latest_version == "24.2.0"
    assert result.candidates[0].command == ["brew", "upgrade", "node"]
    assert result.candidates[0].dependency_impact.used_by == ["pnpm", "yarn"]
