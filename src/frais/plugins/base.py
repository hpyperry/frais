from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

from ..models import PluginScanResult, SystemProfile, UpdateCandidate


class ScannerPlugin(ABC):
    name: str
    enabled_by_default: bool = False
    display_color: str = "white"
    scan_steps: list[str] = []

    @abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def scan(self, system: SystemProfile,
             on_progress: Callable[[int, int], None] | None = None,
             max_workers: int = 10) -> PluginScanResult:
        """Return items that need attention, with candidates for outdated software.

        *on_progress(step_index, items_done)* is called by the plugin to report
        progress through its :attr:`scan_steps`. The CLI uses this to drive
        the progress bar — plugins own the step definitions and pacing.

        *max_workers* controls internal concurrency for plugins that do
        parallel research (e.g. ApplicationsPlugin LLM pipeline).
        """
        raise NotImplementedError

    def scan_all(self, system: SystemProfile,
                 on_progress: Callable[[int, int], None] | None = None,
                 max_workers: int = 10) -> PluginScanResult:
        """Return ALL installed items. Default: same as :meth:`scan`."""
        return self.scan(system, on_progress=on_progress, max_workers=max_workers)

    def update(self, candidate: UpdateCandidate) -> bool:
        """Execute the update for *candidate*. Default: subprocess.run(candidate.command)."""
        if candidate.can_auto_update and candidate.command:
            import subprocess
            subprocess.run(candidate.command, check=False)
            return True
        return False

    def summarize(self, agent, candidate: UpdateCandidate) -> str | None:
        """Generate a human-readable summary. Default: uses LLM."""
        return agent.summarize_candidate(candidate)
