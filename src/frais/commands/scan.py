from __future__ import annotations

import json
import logging
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from ..cli import _ADVICE_CACHE
from ..ignore import load_ignored
from ..plugins.base import ScannerPlugin
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

    if json_output:
        from ..coordinator import run_scan as _run_scan
        result = _run_scan(active, system, show_all=show_all, jobs=10)

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

        console.print_json(json.dumps(result.to_dict(), ensure_ascii=False))
        return

    # Rich progress bar for interactive mode
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        plugin_tasks: dict[str, int] = {}
        plugin_steps: dict[str, int] = {}
        plugin_active: dict[str, ScannerPlugin] = {}

        for name, p in active.items():
            plugin_active[name] = p
            plugin_steps[name] = 0
            step_label = p.scan_steps[0] if p.scan_steps else ""
            plugin_tasks[name] = progress.add_task(f"{name}    {step_label}", total=1)

        def _on_progress(pname: str, step: int, done: int, total: int) -> None:
            task_id = plugin_tasks.get(pname)
            if task_id is None:
                return
            plugin = plugin_active.get(pname)
            if plugin and step != plugin_steps.get(pname):
                plugin_steps[pname] = step
                step_label = (plugin.scan_steps[step]
                              if step < len(plugin.scan_steps)
                              else "")
                progress.update(task_id, description=f"{pname}    {step_label}",
                                total=total, completed=0)
            progress.update(task_id, total=total, completed=done)

        from ..coordinator import run_scan as _run_scan
        result = _run_scan(active, system, show_all=show_all,
                           jobs=10, on_plugin_progress=_on_progress)

        ignored = load_ignored()
        if ignored:
            for pr in result.plugin_results.values():
                pr.items = [it for it in pr.items if it.id not in ignored]
                pr.candidates = [c for c in pr.candidates if c.item.id not in ignored]

        for name in active:
            pr = result.plugin_results.get(name)
            if pr is None:
                continue
            desc = f"{name}    {len(pr.items)} items"
            if pr.candidates:
                desc += f", {len(pr.candidates)} updates"
            progress.update(plugin_tasks[name], description=desc)

    try:
        _ADVICE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = _ADVICE_CACHE.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        tmp_path.replace(_ADVICE_CACHE)
    except OSError as exc:
        logger.warning("failed to save scan cache: %s", exc)

    _print_advise_result(result, len(ignored), show_all=show_all)
