"""Shared output helpers for CLI commands.

Provides consistent JSON and Rich text output so that each command
avoids branching on ``json_mode`` throughout its body.
"""

from __future__ import annotations

import json
import typing

import typer
from rich.console import Console

console = Console()
_stderr_console = Console(stderr=True)


def print_json_success(**kwargs: typing.Any) -> None:
    """Print ``{"ok": true, ...}`` to stdout."""
    kwargs.pop("ok", None)  # reserved — caller cannot override
    data: dict[str, typing.Any] = {"ok": True}
    data.update(kwargs)
    console.print_json(json.dumps(data, ensure_ascii=False))


def exit_with_error(message: str, json_mode: bool, exit_code: int = 1) -> typing.NoReturn:
    """Print an error and exit.

    In JSON mode prints ``{"ok": false, "error": "..."}`` to stdout.
    In CLI mode prints red text to stderr.
    """
    if json_mode:
        console.print_json(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
    else:
        _stderr_console.print(f"[red]Error: {message}[/red]")
    raise typer.Exit(exit_code)
