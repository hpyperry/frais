from __future__ import annotations

import json
import logging
import time

from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from ..ignore import load_ignored
from ..plugins.base import ScannerPlugin
from . import _split_plugins

logger = logging.getLogger(__name__)
console = Console()


def run_scan_phase(active_plugins: dict[str, ScannerPlugin],
                   system, *, show_all: bool = False, jobs: int = 10,
                   json_output: bool = False,
                   cache_path=None
                   ) -> tuple:
    """Run scan with Rich progress, return (result, ignored_count, scan_elapsed).

    When *json_output* is True, the progress bar is skipped.
    When *cache_path* is given, the result is saved to that path.
    """
    from ..coordinator import run_scan

    if json_output:
        result = run_scan(active_plugins, system, show_all=show_all, jobs=jobs)

        ignored_data = load_ignored()
        ignored_count = 0
        if ignored_data:
            for pr in result.plugin_results.values():
                before = len(pr.items) + len(pr.candidates)
                pr.items = [it for it in pr.items if it.id not in ignored_data]
                pr.candidates = [c for c in pr.candidates if c.item.id not in ignored_data]
                ignored_count += before - (len(pr.items) + len(pr.candidates))

        if cache_path:
            _save_cache(result, cache_path)
        return result, ignored_count, {}

    # --- Rich progress bar ---
    plugin_tasks: dict[str, int] = {}
    plugin_steps: dict[str, int] = {}
    plugin_start_times: dict[str, float] = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        for name, p in active_plugins.items():
            plugin_steps[name] = 0
            plugin_start_times[name] = time.monotonic()
            step_label = p.scan_steps[0] if p.scan_steps else ""
            plugin_tasks[name] = progress.add_task(f"{name}    {step_label}", total=1)

        def _on_progress(pname: str, step: int, done: int, total: int) -> None:
            task_id = plugin_tasks.get(pname)
            if task_id is None:
                return
            plugin = active_plugins.get(pname)
            if plugin and step != plugin_steps.get(pname):
                plugin_steps[pname] = step
                step_label = (plugin.scan_steps[step]
                              if step < len(plugin.scan_steps)
                              else "")
                progress.update(task_id, description=f"{pname}    {step_label}",
                                total=total, completed=0)
            progress.update(task_id, total=total, completed=done)

        result = run_scan(active_plugins, system, show_all=show_all,
                          jobs=jobs, on_plugin_progress=_on_progress)

        ignored_data = load_ignored()
        ignored_count = 0
        if ignored_data:
            for pr in result.plugin_results.values():
                before = len(pr.items) + len(pr.candidates)
                pr.items = [it for it in pr.items if it.id not in ignored_data]
                pr.candidates = [c for c in pr.candidates if c.item.id not in ignored_data]
                ignored_count += before - (len(pr.items) + len(pr.candidates))

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

    if cache_path:
        _save_cache(result, cache_path)

    return result, ignored_count, scan_elapsed


def _save_cache(result, path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        tmp_path.replace(path)
    except OSError as exc:
        logger.warning("failed to save scan cache: %s", exc)
