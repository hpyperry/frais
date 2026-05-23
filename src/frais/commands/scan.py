from __future__ import annotations

import logging
import os
import signal
from typing import Annotated

import typer
from rich.console import Console

from ..cli import _ADVICE_CACHE
from ..ignore import load_ignored
from . import _split_plugins
from ._output import exit_with_error, print_json_success
from ._scan_core import run_scan_phase
from .advise import _print_advise_result

logger = logging.getLogger(__name__)
console = Console()


def scan(
    plugins: Annotated[
        str | None,
        typer.Option(
            "--plugins",
            help="Comma-separated plugin names to scan (e.g. homebrew,npm).",
            metavar="NAMES",
        ),
    ] = None,
    show_all: Annotated[
        bool,
        typer.Option("--all", help="Show all installed software, including up-to-date items."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output structured JSON (for agent consumption)."),
    ] = False,
) -> None:
    """Scan installed software for available updates.

    Runs every enabled plugin's scan step and reports discovered items
    and update candidates. With --json, prints machine-readable JSON
    suitable for consumption by external agents.

    Examples:
      frais scan
      frais scan --plugins applications --json
      frais scan --all
    """
    from ..coordinator import select_plugins as _coord_select
    from ..plugins.registry import all_plugins
    from ..system import detect_system

    system = detect_system()
    _explicit = _split_plugins(plugins)
    active = _coord_select(explicit=_explicit)
    if _explicit:
        unknown = set(_explicit) - set(active)
        if not active:
            exit_with_error(f"No available plugins matched: {', '.join(sorted(unknown))}", json_output,
                            reason="no_plugins_matched",
                            hint="Run `frais plugins list --json` to see available plugins.",
                            requested=sorted(unknown))
        if unknown and not json_output:
            console.print(f"[yellow]Unavailable plugins: {', '.join(sorted(unknown))}[/yellow]")

    if not json_output:
        console.print()
        console.print(f"Scanning with: {', '.join(active)}")

    def _on_interrupt(signum, frame):
        try:
            os.write(1, b"\033[?25h\n")
        except OSError:
            pass
        os._exit(130)

    orig_handler = signal.signal(signal.SIGINT, _on_interrupt)
    try:
        result, ignored_count, scan_elapsed = run_scan_phase(
            active, system, show_all=show_all,
            json_output=json_output, cache_path=_ADVICE_CACHE,
        )
    finally:
        signal.signal(signal.SIGINT, orig_handler)

    if json_output:
        print_json_success(**result.to_dict())
    else:
        max_scan_time = max(scan_elapsed.values()) if scan_elapsed else 0.0
        console.print(f"  [dim]Total: {max_scan_time:.1f}s[/dim]")
        _print_advise_result(result, ignored_count, show_all=show_all)
