from __future__ import annotations

import json
import logging
import os
import signal
import time
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.rule import Rule

from ..cli import _ADVICE_CACHE
from ..config import require_config
from ..ignore import load_ignored
from ..llm import LLMClient
from ..models import SourceKind, ScanResult
from ..plugins.base import ScannerPlugin
from . import _split_plugins

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
            console.print(f"  {candidate.item.id}")
            console.print(f"    {candidate.item.name} | {candidate.item.source.value}")
            console.print(
                f"    {candidate.item.current_version or 'unknown'} → "
                f"[green]{candidate.latest_version or 'unknown'}[/green]  [{candidate.recommended_action}]"
            )
            console.print()

    if ignored_count:
        console.print(f"  [dim]{ignored_count} app(s) ignored (use `frais ignore list` to review)[/dim]")


def advise(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print scan results and advice as machine-readable JSON."),
    ] = False,
    apps_only: Annotated[
        bool,
        typer.Option("--apps-only", help="Only advise on Applications; skip package manager plugins."),
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
      frais advise --apps-only
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
        active_plugins = _coord_select(apps_only, _explicit_plugins)

        console.print()
        plugin_labels = ", ".join(active_plugins)
        console.print(
            f"  [bold cyan]OS:[/] {system.os_name} {system.os_version}  "
            f"[bold cyan]Arch:[/] {system.arch}  "
            f"[bold cyan]Plugins:[/] {plugin_labels}"
        )
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
            plugin_start_times: dict[str, float] = {}

            for name in active_plugins:
                p = all_plugins()[name]
                plugin_active[name] = p
                plugin_steps[name] = 0
                plugin_start_times[name] = time.monotonic()
                step_label = p.scan_steps[0] if p.scan_steps else ""
                plugin_tasks[name] = progress.add_task(f"{name}    {step_label}", total=1)

            def _on_plugin_progress(pname: str, step: int, done: int, total: int) -> None:
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

            from ..coordinator import run_scan
            result = run_scan(plugin_active, system, show_all=show_all,
                              jobs=jobs, on_plugin_progress=_on_plugin_progress)

            ignored = load_ignored()
            if ignored:
                for pr in result.plugin_results.values():
                    pr.items = [it for it in pr.items if it.id not in ignored]
                    pr.candidates = [c for c in pr.candidates if c.item.id not in ignored]

            scan_elapsed: dict[str, float] = {}
            for name in active_plugins:
                pr = result.plugin_results.get(name)
                if pr is None:
                    continue
                elapsed = time.monotonic() - plugin_start_times.get(name, 0)
                scan_elapsed[name] = elapsed
                desc = f"{name}    {len(pr.items)} items"
                if pr.candidates:
                    desc += f", {len(pr.candidates)} updates"
                progress.update(plugin_tasks[name], description=desc)

            max_scan_time = max(scan_elapsed.values()) if scan_elapsed else 0.0

            all_candidates = result.all_candidates
            summarize_elapsed = 0.0
            if all_candidates:
                summarize_task = progress.add_task("Summaries", total=len(all_candidates))
                candidate_plugin_map: dict[int, str] = {}
                for pname, pr in result.plugin_results.items():
                    for c in pr.candidates:
                        candidate_plugin_map[id(c)] = pname
                t0 = time.monotonic()
                run_summaries(llm, all_candidates, candidate_plugin_map,
                              plugin_active, max_workers=jobs,
                              on_progress=lambda: progress.advance(summarize_task))
                summarize_elapsed = time.monotonic() - t0

            total_time = max_scan_time + summarize_elapsed
            console.print(f"  [dim]Total: {total_time:.1f}s[/dim]")

        if json_output:
            console.print_json(json.dumps(result.to_dict(), ensure_ascii=False))
            return

        try:
            _ADVICE_CACHE.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = _ADVICE_CACHE.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
            tmp_path.replace(_ADVICE_CACHE)
            logger.info("advice cache saved to %s", _ADVICE_CACHE)
        except OSError as exc:
            logger.warning("failed to save advice cache: %s", exc)

        _print_advise_result(result, len(ignored), show_all=show_all)

    finally:
        signal.signal(signal.SIGINT, orig_handler)
