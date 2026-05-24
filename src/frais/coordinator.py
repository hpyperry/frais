from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed

from .llm import LLMClient
from .models import PluginScanResult, ScanResult, SystemProfile, UpdateCandidate
from .plugins.base import ScannerPlugin

logger = logging.getLogger(__name__)


def select_plugins(explicit: list[str] | None = None) -> dict[str, ScannerPlugin]:
    """Return enabled plugins filtered by CLI flags and persisted config."""
    from .plugins.registry import all_plugins
    from .store.plugin_store import load_plugins_config

    available = all_plugins()
    if explicit:
        persisted = load_plugins_config()
        result: dict[str, ScannerPlugin] = {}
        for name in explicit:
            if name not in available:
                logger.warning("unknown plugin: %s", name)
                continue
            if name in persisted and not persisted[name]:
                logger.warning("plugin is disabled: %s", name)
                continue
            result[name] = available[name]
        return result

    plugin_result: dict[str, ScannerPlugin] = {}
    persisted = load_plugins_config()
    for name, plugin in available.items():
        if name in persisted:
            if persisted[name]:
                plugin_result[name] = plugin
        elif plugin.enabled_by_default:
            plugin_result[name] = plugin
    return plugin_result


def run_scan(plugins: dict[str, ScannerPlugin],
             system: SystemProfile,
             show_all: bool = False,
             jobs: int = 10,
             on_plugin_progress: Callable[[str, int, int, int], None] | None = None,
             on_plugin_done: Callable[[str, PluginScanResult], None] | None = None,
             ) -> ScanResult:
    """Scan all plugins concurrently. Each plugin drives its own progress callback.

    *on_plugin_progress(pname, step, done, total)* fires during scan.
    *on_plugin_done(pname, result)* fires as each plugin finishes.
    """
    result = ScanResult(system=system)

    with ThreadPoolExecutor(max_workers=max(1, len(plugins))) as pool:
        future_to_name: dict[Future[PluginScanResult], str] = {}
        for name, plugin in plugins.items():
            scan_fn = plugin.scan_all if show_all else plugin.scan

            def _progress_wrapper(step: int, done: int, total: int, pname: str = name) -> None:
                if on_plugin_progress:
                    on_plugin_progress(pname, step, done, total)

            future_to_name[pool.submit(scan_fn, system, on_progress=_progress_wrapper,
                                       max_workers=jobs)] = name

        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                pr = future.result()
            except Exception as exc:
                logger.warning("scan failed for %s: %s", name, exc, exc_info=True)
                from .models import PluginScanResult
                pr = PluginScanResult(skipped=[str(exc)])
            result.plugin_results[name] = pr
            if on_plugin_done:
                on_plugin_done(name, pr)

    return result


def run_summaries(llm: LLMClient,
                  candidates: list[UpdateCandidate],
                  candidate_plugins: dict[int, str],
                  plugins: dict[str, ScannerPlugin],
                  max_workers: int = 5,
                  on_progress: Callable[[], None] | None = None) -> None:
    """Generate summaries for all candidates via their owning plugins.

    *candidate_plugins* maps ``id(candidate)`` → plugin name.
    """
    if not candidates:
        return

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = []
        for c in candidates:
            pname = candidate_plugins.get(id(c))
            plugin = plugins.get(pname) if pname else None
            if plugin:
                futures.append(pool.submit(plugin.summarize, llm, c))
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                logger.warning("summary failed: %s", exc, exc_info=True)
            if on_progress:
                on_progress()
