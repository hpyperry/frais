from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

import typer

from ...models import PluginScanResult, SourceKind, SystemProfile, UpdateCandidate
from ..base import ScannerPlugin
from .app_store import resolve_app_store_command
from .discovery import scan_applications
from .research import research_application_update

logger = logging.getLogger(__name__)


class ApplicationsPlugin(ScannerPlugin):
    name = "applications"
    enabled_by_default = True
    display_color = "cyan"
    scan_steps = ["discovering apps", "researching latest versions"]

    def is_available(self) -> bool:
        return True

    def scan(self, system: SystemProfile,
             on_progress: Callable[[int, int, int], None] | None = None,
             max_workers: int = 10) -> PluginScanResult:
        # Step 1: discover all installed applications
        items = scan_applications(system.applications_paths)
        logger.info("applications scan found=%d", len(items))
        if on_progress:
            on_progress(0, len(items), len(items))

        # Step 2: research latest versions for non-App-Store apps
        from ...llm import get_client
        from ...store.config_store import require_config

        try:
            config = require_config()
            llm = get_client(config)
        except (ValueError, RuntimeError) as exc:
            logger.warning("LLM not available for applications research: %s", exc, exc_info=True)
            return PluginScanResult(items=items, candidates=[], skipped=[str(exc)])

        candidates: list[UpdateCandidate] = []
        to_research = [it for it in items if it.source != SourceKind.APP_STORE]
        researched = 0

        if on_progress:
            on_progress(1, 0, len(to_research))

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(research_application_update, llm, it): it for it in to_research}
            for future in as_completed(futures):
                researched += 1
                try:
                    candidate = future.result()
                except Exception as exc:
                    item_for_log = futures[future]
                    logger.warning("research failed for %s: %s", item_for_log.name, exc, exc_info=True)
                    if on_progress:
                        on_progress(1, researched, len(to_research))
                    continue
                if candidate:
                    candidates.append(candidate)
                if on_progress:
                    on_progress(1, researched, len(to_research))

        logger.info("applications research done candidates=%d", len(candidates))
        llm.close()
        return PluginScanResult(items=items, candidates=candidates)

    def update(self, candidate: UpdateCandidate) -> bool:
        if candidate.item.source == SourceKind.APP_STORE:
            cmd, can_auto = resolve_app_store_command(candidate.item)
            if can_auto and cmd:
                subprocess.run(cmd, check=False)
                return True
        if candidate.can_auto_update and candidate.command:
            return super().update(candidate)
        if candidate.item.path:
            if typer.confirm("    Open app for manual update?", default=False):
                subprocess.run(["open", candidate.item.path], check=False)
                return True
            return False
        return False
