from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from ..ignore_filter import apply_ignore_filter
from ..models import ScanResult, SystemProfile
from ..plugins.base import ScannerPlugin
from ..store.scan_cache import save_scan_cache

logger = logging.getLogger(__name__)
console = Console()


@dataclass(slots=True)
class ScanPhaseResult:
    scan_result: ScanResult
    ignored_count: int
    scan_elapsed: dict[str, float]

    def __iter__(self):
        yield self.scan_result
        yield self.ignored_count
        yield self.scan_elapsed


def run_scan_phase(active_plugins: dict[str, ScannerPlugin],
                   system: SystemProfile, *, show_all: bool = False, jobs: int = 10,
                   json_output: bool = False,
                   cache_path: Path | None = None,
                   ) -> ScanPhaseResult:
    """Run scan with Rich progress.

    When *json_output* is True, the progress bar is skipped.
    When *cache_path* is given, the result is saved to that path.
    """
    from ..coordinator import run_scan

    if json_output:
        result = run_scan(active_plugins, system, show_all=show_all, jobs=jobs)
        filter_result = apply_ignore_filter(result)
        if cache_path:
            save_scan_cache(filter_result.scan_result, cache_path)
        return ScanPhaseResult(
            scan_result=filter_result.scan_result,
            ignored_count=filter_result.ignored_count,
            scan_elapsed={},
        )

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

        scan_elapsed: dict[str, float] = {}

        from ..models import PluginScanResult

        def _on_plugin_done(pname: str, pr: PluginScanResult) -> None:
            task_id = plugin_tasks.get(pname)
            if task_id is not None:
                scan_elapsed[pname] = time.monotonic() - plugin_start_times.get(pname, 0)
                desc = f"{pname}    {len(pr.items)} items"
                if pr.candidates:
                    desc += f", {len(pr.candidates)} updates"
                progress.update(task_id, description=desc, total=1, completed=1)

        result = run_scan(active_plugins, system, show_all=show_all,
                          jobs=jobs, on_plugin_progress=_on_progress,
                          on_plugin_done=_on_plugin_done)

        filter_result = apply_ignore_filter(result)

    if cache_path:
        save_scan_cache(filter_result.scan_result, cache_path)

    return ScanPhaseResult(
        scan_result=filter_result.scan_result,
        ignored_count=filter_result.ignored_count,
        scan_elapsed=scan_elapsed,
    )


_save_cache = save_scan_cache
