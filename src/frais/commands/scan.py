from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from ..cli import _ADVICE_CACHE
from ..ignore import load_ignored
from . import _split_plugins
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
    active = _coord_select(apps_only=False, explicit=_explicit)

    if not json_output:
        console.print()
        console.print(f"Scanning with: {', '.join(active)}")

    def _on_progress(pname: str, step: int, done: int, total: int) -> None:
        if not json_output:
            p = active.get(pname)
            label = (p.scan_steps[step] if p and step < len(p.scan_steps) else pname)
            console.print(f"  {pname}: {label} ({done}/{total})")

    from ..coordinator import run_scan as _run_scan
    result = _run_scan(active, system, show_all=show_all,
                       jobs=10, on_plugin_progress=_on_progress)

    ignored = load_ignored()
    if ignored:
        for pr in result.plugin_results.values():
            pr.items = [it for it in pr.items if it.id not in ignored]
            pr.candidates = [c for c in pr.candidates if c.item.id not in ignored]

    try:
        _ADVICE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = _ADVICE_CACHE.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        tmp_path.replace(_ADVICE_CACHE)
    except OSError as exc:
        logger.warning("failed to save scan cache: %s", exc)

    if json_output:
        console.print_json(json.dumps(result.to_dict(), ensure_ascii=False))
    else:
        _print_advise_result(result, len(ignored), show_all=show_all)
