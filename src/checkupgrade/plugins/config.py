from __future__ import annotations

import tomllib
from pathlib import Path

PLUGINS_CONFIG_PATH = Path.home() / ".config" / "checkupgrade" / "plugins.toml"


def load_plugins_config(path: Path = PLUGINS_CONFIG_PATH) -> dict[str, bool]:
    """Return persisted plugin enable/disable states. Missing = use default."""
    if not path.exists():
        return {}
    with path.open("rb") as f:
        data = tomllib.load(f)
    plugins = data.get("plugins", {})
    return {k: bool(v) for k, v in plugins.items()}


def save_plugin_state(name: str, enabled: bool, path: Path = PLUGINS_CONFIG_PATH) -> None:
    """Persist a single plugin's enabled state, creating the file if needed."""
    config = load_plugins_config(path)
    config[name] = enabled
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["[plugins]"]
    for k in sorted(config):
        lines.append(f"{k} = {'true' if config[k] else 'false'}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def remove_plugin_state(name: str, path: Path = PLUGINS_CONFIG_PATH) -> bool:
    """Remove a plugin from persisted config. Returns False if not present."""
    config = load_plugins_config(path)
    if name not in config:
        return False
    del config[name]
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["[plugins]"]
    for k in sorted(config):
        lines.append(f"{k} = {'true' if config[k] else 'false'}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True
