"""Ignore list commands: list, add, remove."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console

from ..store.ignore_store import add_ignored, init_ignored, load_ignored, remove_ignored
from ._output import print_json_success

console = Console()


def ignore_list(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output structured JSON (for agent consumption)."),
    ] = False,
) -> None:
    """List all ignored app IDs."""
    init_ignored()
    ids = load_ignored()
    if json_output:
        print_json_success(ignored=sorted(ids), count=len(ids))
        return
    if not ids:
        console.print("No ignored apps.")
        return
    console.print(f"Ignored apps ({len(ids)}):")
    for app_id in sorted(ids):
        console.print(f"  {app_id}")


def ignore_add(
    app_id: Annotated[str, typer.Argument(help="App ID (bundle id) to ignore.")],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output structured JSON (for agent consumption)."),
    ] = False,
) -> None:
    """Add an app to the ignore list."""
    init_ignored()
    was_added = add_ignored(app_id)
    if json_output:
        print_json_success(app_id=app_id, action="added" if was_added else "already_ignored")
        return
    if was_added:
        console.print(f"Added: {app_id}")
    else:
        console.print(f"Already ignored: {app_id}")


def ignore_remove(
    app_id: Annotated[str, typer.Argument(help="App ID (bundle id) to remove from ignore list.")],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output structured JSON (for agent consumption)."),
    ] = False,
) -> None:
    """Remove an app from the ignore list."""
    init_ignored()
    was_removed = remove_ignored(app_id)
    if json_output:
        print_json_success(app_id=app_id, action="removed" if was_removed else "not_in_list")
        return
    if was_removed:
        console.print(f"Removed: {app_id}")
    else:
        console.print(f"Not in ignore list: {app_id}")
