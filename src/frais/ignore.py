from __future__ import annotations

from pathlib import Path

IGNORE_PATH = Path.home() / ".frais" / "config" / "ignore.txt"


def load_ignored(path: Path = IGNORE_PATH) -> set[str]:
    if not path.exists():
        return set()
    lines = path.read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip() and not line.strip().startswith("#")}


def init_ignored(path: Path = IGNORE_PATH) -> None:
    """Create ignore.txt if it does not exist."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")


def save_ignored(ids: set[str], path: Path = IGNORE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(sorted(ids)) + "\n", encoding="utf-8")


def add_ignored(app_id: str, path: Path = IGNORE_PATH) -> bool:
    ids = load_ignored(path)
    if app_id in ids:
        return False
    ids.add(app_id)
    save_ignored(ids, path)
    return True


def remove_ignored(app_id: str, path: Path = IGNORE_PATH) -> bool:
    ids = load_ignored(path)
    if app_id not in ids:
        return False
    ids.discard(app_id)
    save_ignored(ids, path)
    return True
