from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from ._output import exit_with_error, print_json_success

console = Console()


def plugins_list(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output structured JSON (for agent consumption)."),
    ] = False,
) -> None:
    """List all known plugins and their status."""
    from ..plugins.registry import all_plugins
    from ..store.plugin_store import init_plugins_config, load_plugins_config

    init_plugins_config()
    persisted = load_plugins_config()

    if json_output:
        print_json_success(plugins=_plugin_rows(persisted))
        return

    table = Table("Plugin", "Available", "Default", "Effective")
    for row in _plugin_rows(persisted):
        table.add_row(row["name"], row["available"], row["default"], row["effective"])
    console.print(table)


def plugins_enable(
    name: Annotated[str, typer.Argument(help="Plugin name, for example: homebrew")],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output structured JSON (for agent consumption)."),
    ] = False,
) -> None:
    """Persistently enable a plugin."""
    _set_plugin_state(name=name, enabled=True, json_output=json_output)


def plugins_disable(
    name: Annotated[str, typer.Argument(help="Plugin name, for example: homebrew")],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output structured JSON (for agent consumption)."),
    ] = False,
) -> None:
    """Persistently disable a plugin."""
    _set_plugin_state(name=name, enabled=False, json_output=json_output)


def _plugin_rows(persisted: dict[str, bool]) -> list[dict[str, str]]:
    from ..plugins.registry import all_plugins

    rows: list[dict[str, str]] = []
    for name, plugin in all_plugins().items():
        rows.append({
            "name": name,
            "available": "yes" if plugin.is_available() else "no",
            "default": "enabled" if plugin.enabled_by_default else "disabled",
            "effective": "enabled" if persisted.get(name, plugin.enabled_by_default) else "disabled",
        })
    return rows


def _set_plugin_state(name: str, enabled: bool, json_output: bool) -> None:
    from ..plugins.registry import all_plugins
    from ..store.plugin_store import init_plugins_config, save_plugin_state

    init_plugins_config()
    if name not in all_plugins():
        exit_with_error(
            f"Unknown plugin: {name}",
            json_output,
            reason="unknown_plugin",
            hint="Run `frais plugins list --json` to see available plugins.",
            plugin_name=name,
        )

    save_plugin_state(name, enabled)
    action = "enabled" if enabled else "disabled"
    if json_output:
        print_json_success(plugin=name, action=action)
        return
    console.print(f"Plugin [bold]{name}[/bold] {action} (persisted).")
