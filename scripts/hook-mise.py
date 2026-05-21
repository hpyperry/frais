from __future__ import annotations

from importlib.metadata import entry_points


def _plugin_hidden_imports() -> list[str]:
    """Discover all plugin modules from entry points at build time."""
    imports: list[str] = []
    for ep in entry_points(group="mise.plugins"):
        module = ep.value.split(":")[0]
        imports.append(module)
    return imports


hiddenimports = _plugin_hidden_imports()
