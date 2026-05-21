from __future__ import annotations

from pathlib import Path

import pytest

from checkupgrade.ignore import add_ignored, load_ignored, remove_ignored, save_ignored


def test_load_ignored_empty_when_no_file(tmp_path: Path) -> None:
    path = tmp_path / "nonexistent" / "ignore.txt"
    assert load_ignored(path) == set()


def test_load_ignored_skips_comments_and_blanks(tmp_path: Path) -> None:
    path = tmp_path / "ignore.txt"
    path.write_text("# comment\ncom.example.app\n\n  \n# another\ncom.other.app\n", encoding="utf-8")
    result = load_ignored(path)
    assert result == {"com.example.app", "com.other.app"}


def test_load_ignored_strips_whitespace(tmp_path: Path) -> None:
    path = tmp_path / "ignore.txt"
    path.write_text("  com.example.app  \n", encoding="utf-8")
    assert load_ignored(path) == {"com.example.app"}


def test_save_ignored_creates_parent_dirs(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "dir" / "ignore.txt"
    save_ignored({"com.a.app", "com.b.app"}, path)
    assert path.exists()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines == ["com.a.app", "com.b.app"]


def test_save_ignored_sorted(tmp_path: Path) -> None:
    path = tmp_path / "ignore.txt"
    save_ignored({"com.c.app", "com.a.app", "com.b.app"}, path)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines == ["com.a.app", "com.b.app", "com.c.app"]


def test_add_ignored_new(tmp_path: Path) -> None:
    path = tmp_path / "ignore.txt"
    assert add_ignored("com.example.app", path) is True
    assert load_ignored(path) == {"com.example.app"}


def test_add_ignored_duplicate(tmp_path: Path) -> None:
    path = tmp_path / "ignore.txt"
    add_ignored("com.example.app", path)
    assert add_ignored("com.example.app", path) is False
    assert load_ignored(path) == {"com.example.app"}


def test_remove_ignored_existing(tmp_path: Path) -> None:
    path = tmp_path / "ignore.txt"
    save_ignored({"com.a.app", "com.b.app"}, path)
    assert remove_ignored("com.a.app", path) is True
    assert load_ignored(path) == {"com.b.app"}


def test_remove_ignored_not_found(tmp_path: Path) -> None:
    path = tmp_path / "ignore.txt"
    assert remove_ignored("com.nonexistent", path) is False


def test_add_then_remove(tmp_path: Path) -> None:
    path = tmp_path / "ignore.txt"
    add_ignored("com.example.app", path)
    add_ignored("com.other.app", path)
    assert load_ignored(path) == {"com.example.app", "com.other.app"}
    remove_ignored("com.example.app", path)
    assert load_ignored(path) == {"com.other.app"}


def test_save_ignored_raises_on_unwritable_path(tmp_path: Path) -> None:
    path = tmp_path / "readonly" / "ignore.txt"
    path.parent.mkdir()
    path.parent.chmod(0o444)  # read-only
    try:
        with pytest.raises(OSError):
            save_ignored({"com.example.app"}, path)
    finally:
        path.parent.chmod(0o755)
