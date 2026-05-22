from __future__ import annotations

import json
import logging
import os
import signal
import time
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn, TimeElapsedColumn
from rich.rule import Rule

from ..cli import _ADVICE_CACHE
from ..config import require_config
from ..ignore import load_ignored
from ..llm import LLMClient
from ..models import SourceKind, ScanResult
from . import _split_plugins
from ._scan_core import _save_cache, run_scan_phase

logger = logging.getLogger(__name__)
console = Console()


def _print_advise_result(result: ScanResult, ignored_count: int = 0,
                         show_all: bool = False) -> None:
    from ..plugins.registry import all_plugins

    candidate_item_ids = {c.item.id for c in result.all_candidates}
    plugins = all_plugins()

    for name, pr in result.plugin_results.items():
        plugin = plugins.get(name)
        color = plugin.display_color if plugin else "white"
        if show_all:
            current_items = [it for it in pr.items if it.id not in candidate_item_ids]
            if current_items:
                console.print(Rule(f"[bold]{name}[/] — {len(current_items)} up to date", style=color))
                for item in sorted(current_items, key=lambda x: x.name.lower()):
                    current = item.current_version or "unknown"
                    source = item.source.value
                    console.print(f"  {item.id}")
                    console.print(f"    {item.name} | {source} | {current}  [dim]up to date[/dim]")
                console.print()
        for skipped in pr.skipped:
            console.print(f"  [dim]Skipped ({name}): {skipped}[/dim]")

    if result.all_candidates:
        console.print(Rule(f"[bold]Updates available[/] ({len(result.all_candidates)})", style="green"))
        console.print()
        for candidate in result.all_candidates:
            console.print(f"  [bold]{candidate.item.name}[/bold]  [dim]({candidate.item.id})[/dim]")
            console.print(
                f"  {candidate.item.current_version or 'unknown'} → "
                f"[green]{candidate.latest_version or 'unknown'}[/green]"
            )
            if candidate.ai_summary:
                console.print(f"  [bold cyan]AI Analysis[/]")
                console.print(f"    {candidate.ai_summary}")
            console.print()

    if ignored_count:
        console.print(f"  [dim]{ignored_count} app(s) ignored (use `frais ignore list` to review)[/dim]")


def advise(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print scan results and advice as machine-readable JSON."),
    ] = False,
    plugins: Annotated[
        str | None,
        typer.Option(
            "--plugins",
            help="Comma-separated plugin names to advise on (e.g. homebrew,npm).",
            metavar="NAMES",
        ),
    ] = None,
    jobs: Annotated[
        int,
        typer.Option(
            "--jobs",
            "-j",
            help="Number of concurrent LLM requests.",
            min=1,
            max=20,
        ),
    ] = 10,
    show_all: Annotated[
        bool,
        typer.Option("--all", help="Show all installed software, including up-to-date items."),
    ] = False,
) -> None:
    """Scan and generate LLM-powered update advice.

    Requires a configured LLM provider (run `frais config manage` first).
    The LLM is used for release research and summaries; missing or
    unreliable evidence is reported as unknown instead of being invented.

    Examples:
      frais advise
      frais advise --all
      frais advise --json
      frais advise -j 5
    """
    from ..coordinator import run_summaries, select_plugins as _coord_select
    from ..plugins.registry import all_plugins
    from ..system import detect_system

    try:
        config = require_config()
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    logger.info("advise using provider=%s model=%s jobs=%d", config.provider.name, config.model, jobs)
    llm = LLMClient(config)

    def _on_interrupt(signum, frame):
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        os.write(1, b"\033[?25h\n")
        os._exit(130)

    orig_handler = signal.signal(signal.SIGINT, _on_interrupt)
    try:
        system = detect_system()
        _explicit_plugins = _split_plugins(plugins)
        active_plugins = _coord_select(_explicit_plugins)
        if _explicit_plugins:
            unknown = set(_explicit_plugins) - set(active_plugins)
            if unknown:
                console.print(f"[yellow]Unavailable plugins: {', '.join(sorted(unknown))}[/yellow]")
            if not active_plugins:
                raise typer.Exit(1)

        console.print()
        plugin_labels = ", ".join(active_plugins)
        console.print(
            f"  [bold cyan]OS:[/] {system.os_name} {system.os_version}  "
            f"[bold cyan]Arch:[/] {system.arch}  "
            f"[bold cyan]Plugins:[/] {plugin_labels}"
        )
        console.print()

        result, ignored_count, scan_elapsed = run_scan_phase(
            active_plugins, system, show_all=show_all, jobs=jobs,
            json_output=json_output,
        )

        max_scan_time = max(scan_elapsed.values()) if scan_elapsed else 0.0

        # Summaries
        all_candidates = result.all_candidates
        summarize_elapsed = 0.0
        if all_candidates:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                console=console,
            ) as summary_progress:
                summarize_task = summary_progress.add_task("Summaries", total=len(all_candidates))
                candidate_plugin_map: dict[int, str] = {}
                for pname, pr in result.plugin_results.items():
                    for c in pr.candidates:
                        candidate_plugin_map[id(c)] = pname
                t0 = time.monotonic()
                run_summaries(llm, all_candidates, candidate_plugin_map,
                              active_plugins, max_workers=jobs,
                              on_progress=lambda: summary_progress.advance(summarize_task))
                summarize_elapsed = time.monotonic() - t0

            total_time = max_scan_time + summarize_elapsed
            console.print(f"  [dim]Total: {total_time:.1f}s[/dim]")

        _save_cache(result, _ADVICE_CACHE)

        if json_output:
            console.print_json(json.dumps(result.to_dict(), ensure_ascii=False))
        else:
            _print_advise_result(result, ignored_count, show_all=show_all)

    finally:
        signal.signal(signal.SIGINT, orig_handler)


