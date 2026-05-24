"""Rich progress bar rendering for the scan phase."""

import time
from collections.abc import Callable

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)

from ..models import PluginScanResult
from ..plugins.base import ScannerPlugin

console = Console()


def setup_plugin_progress(active_plugins: dict[str, ScannerPlugin]) -> tuple[
    Progress, dict[str, TaskID], dict[str, int], dict[str, float],
]:
    """Create a Rich Progress context with one task row per active plugin.

    Returns (progress_context, plugin_tasks, plugin_steps, plugin_start_times).
    The caller must use this as a context manager.
    """
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    )
    plugin_tasks: dict[str, TaskID] = {}
    plugin_steps: dict[str, int] = {}
    plugin_start_times: dict[str, float] = {}

    for name, p in active_plugins.items():
        plugin_steps[name] = 0
        plugin_start_times[name] = time.monotonic()
        step_label = p.scan_steps[0] if p.scan_steps else ""
        plugin_tasks[name] = progress.add_task(f"{name}    {step_label}", total=1)

    return progress, plugin_tasks, plugin_steps, plugin_start_times


def make_progress_callback(
    active_plugins: dict[str, ScannerPlugin],
    plugin_tasks: dict[str, TaskID],
    plugin_steps: dict[str, int],
    progress: Progress,
) -> Callable[[str, int, int, int], None]:
    """Build a progress callback for Coordinator.run_scan."""

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

    return _on_progress


def make_done_callback(
    active_plugins: dict[str, ScannerPlugin],
    plugin_tasks: dict[str, TaskID],
    plugin_start_times: dict[str, float],
    progress: Progress,
    scan_elapsed: dict[str, float],
) -> Callable[[str, PluginScanResult], None]:
    """Build a completion callback for Coordinator.run_scan."""

    def _on_plugin_done(pname: str, pr: PluginScanResult) -> None:
        task_id = plugin_tasks.get(pname)
        if task_id is not None:
            scan_elapsed[pname] = time.monotonic() - plugin_start_times.get(pname, 0)
            desc = f"{pname}    {len(pr.items)} items"
            if pr.candidates:
                desc += f", {len(pr.candidates)} updates"
            progress.update(task_id, description=desc, total=1, completed=1)

    return _on_plugin_done
