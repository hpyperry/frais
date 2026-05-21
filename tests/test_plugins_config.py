from __future__ import annotations

from pathlib import Path

import pytest

from checkupgrade.plugins.config import load_plugins_config, remove_plugin_state, save_plugin_state


def test_load_plugins_config_empty_when_no_file(tmp_path: Path) -> None:
    path = tmp_path / "nonexistent" / "plugins.toml"
    assert load_plugins_config(path) == {}


def test_load_plugins_config_reads_toml(tmp_path: Path) -> None:
    path = tmp_path / "plugins.toml"
    path.write_text("[plugins]\nhomebrew = false\nnpm = true\n", encoding="utf-8")
    result = load_plugins_config(path)
    assert result == {"homebrew": False, "npm": True}


def test_load_plugins_config_returns_empty_when_no_section(tmp_path: Path) -> None:
    path = tmp_path / "plugins.toml"
    path.write_text("[other]\nkey = 1\n", encoding="utf-8")
    assert load_plugins_config(path) == {}


def test_save_plugin_state_creates_file(tmp_path: Path) -> None:
    path = tmp_path / "plugins.toml"
    save_plugin_state("homebrew", False, path)
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "[plugins]" in content
    assert "homebrew = false" in content


def test_save_plugin_state_creates_parent_dirs(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "dir" / "plugins.toml"
    save_plugin_state("homebrew", True, path)
    assert path.exists()


def test_save_plugin_state_updates_existing(tmp_path: Path) -> None:
    path = tmp_path / "plugins.toml"
    save_plugin_state("homebrew", False, path)
    save_plugin_state("npm", True, path)
    result = load_plugins_config(path)
    assert result == {"homebrew": False, "npm": True}


def test_save_plugin_state_overwrites_existing(tmp_path: Path) -> None:
    path = tmp_path / "plugins.toml"
    save_plugin_state("homebrew", False, path)
    save_plugin_state("homebrew", True, path)
    result = load_plugins_config(path)
    assert result == {"homebrew": True}


def test_remove_plugin_state_existing(tmp_path: Path) -> None:
    path = tmp_path / "plugins.toml"
    save_plugin_state("homebrew", False, path)
    save_plugin_state("npm", True, path)
    removed = remove_plugin_state("homebrew", path)
    assert removed
    result = load_plugins_config(path)
    assert result == {"npm": True}


def test_remove_plugin_state_not_found(tmp_path: Path) -> None:
    path = tmp_path / "plugins.toml"
    save_plugin_state("homebrew", False, path)
    removed = remove_plugin_state("nonexistent", path)
    assert not removed
    result = load_plugins_config(path)
    assert result == {"homebrew": False}


def test_load_plugins_config_malformed_toml(tmp_path: Path) -> None:
    import tomllib

    path = tmp_path / "plugins.toml"
    path.write_text("malformed [[[ toml", encoding="utf-8")
    with pytest.raises(tomllib.TOMLDecodeError):
        load_plugins_config(path)


def test_save_preserves_sorted_order(tmp_path: Path) -> None:
    path = tmp_path / "plugins.toml"
    save_plugin_state("npm", False, path)
    save_plugin_state("applications", True, path)
    save_plugin_state("homebrew", True, path)
    lines = path.read_text(encoding="utf-8").splitlines()
    content_lines = [l for l in lines if "=" in l]
    assert content_lines == [
        "applications = true",
        "homebrew = true",
        "npm = false",
    ]
