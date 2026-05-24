from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ..ignore_filter import apply_ignore_filter
from ..models import ScanResult, SystemProfile
from ..plugins.base import ScannerPlugin
from ..store.scan_cache import save_scan_cache

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ScanPhaseResult:
    scan_result: ScanResult
    ignored_count: int
    scan_elapsed: dict[str, float]

    def __iter__(self):  # type: ignore[no-untyped-def]
        yield self.scan_result
        yield self.ignored_count
        yield self.scan_elapsed


def run_scan_phase(active_plugins: dict[str, ScannerPlugin],
                   system: SystemProfile, *, show_all: bool = False, jobs: int = 10,
                   json_output: bool = False,
                   cache_path: Path | None = None,
                   ) -> ScanPhaseResult:
    """Run scan with Rich progress (or JSON-only path).

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

    from ..ui.scan_progress import (
        make_done_callback,
        make_progress_callback,
        setup_plugin_progress,
    )

    progress, plugin_tasks, plugin_steps, plugin_start_times = setup_plugin_progress(active_plugins)
    scan_elapsed: dict[str, float] = {}

    with progress:
        _on_progress = make_progress_callback(active_plugins, plugin_tasks, plugin_steps, progress)
        _on_plugin_done = make_done_callback(active_plugins, plugin_tasks, plugin_start_times, progress, scan_elapsed)

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
