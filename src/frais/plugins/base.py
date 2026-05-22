from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import PluginScanResult, SoftwareItem, SystemProfile, UpdateCandidate


class ScannerPlugin(ABC):
    name: str
    enabled_by_default: bool = False
    display_color: str = "white"

    @abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def scan(self, system: SystemProfile) -> PluginScanResult:
        """Return items that need attention. For --all mode see scan_all()."""
        raise NotImplementedError

    def scan_all(self, system: SystemProfile) -> PluginScanResult:
        """Return ALL installed items. Default: same as scan()."""
        return self.scan(system)

    def research(self, agent, item: SoftwareItem) -> UpdateCandidate | None:
        """Research whether a newer version exists for *item*. Override to enable.

        The *agent* parameter is an :class:`LLMClient` for LLM-based research.
        Plugins may ignore it and use their own strategy (e.g. a package-registry
        API).  Return ``None`` when the item is already up-to-date or research is
        not possible.
        """
        return None

    @property
    def needs_research(self) -> bool:
        """True when the plugin overrides :meth:`research`."""
        return type(self).research is not ScannerPlugin.research

    def update(self, candidate: UpdateCandidate) -> bool:
        """Execute the update for *candidate*. Return True on success.

        The default runs ``candidate.command`` via ``subprocess``.
        Override for plugin-specific update behavior (e.g. opening the
        App Store page).
        """
        if candidate.can_auto_update and candidate.command:
            import subprocess
            subprocess.run(candidate.command, check=False)
            return True
        return False

    @property
    def needs_update(self) -> bool:
        """True when the plugin overrides :meth:`update`."""
        return type(self).update is not ScannerPlugin.update

    def summarize(self, agent, candidate: UpdateCandidate) -> str | None:
        """Generate a human-readable summary for a candidate. Default: LLM."""
        return agent.summarize_candidate(candidate)
