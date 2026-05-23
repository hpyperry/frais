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


def exit_with_error(message: str, json_mode: bool, exit_code: int = 1,
                    reason: str = "", hint: str = "",
                    **extra: typing.Any) -> typing.NoReturn:
    """Print an error and exit.

    In JSON mode prints ``{"ok": false, "error": "...", "reason": "...", "hint": "..."}`` to stdout.
    In CLI mode prints red text to stderr (reason and hint shown as dim text).

    *reason* is a stable machine-readable enum value the LLM can branch on.
    *hint* tells the LLM what action to take next.
    *extra* carries context fields (e.g. item_id, plugin_name) for the JSON output.
    """
    if json_mode:
        data: dict[str, typing.Any] = {"ok": False, "error": message}
        if reason:
            data["reason"] = reason
        if hint:
            data["hint"] = hint
        data.update(extra)
        console.print_json(json.dumps(data, ensure_ascii=False))
    else:
        _stderr_console.print(f"[red]Error: {message}[/red]")
        if hint:
            _stderr_console.print(f"[dim]{hint}[/dim]")
    raise typer.Exit(exit_code)
