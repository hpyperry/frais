from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import SystemProfile, UpdateCandidate


class ScannerPlugin(ABC):
    name: str
    enabled_by_default: bool = False

    @abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def scan(self, system: SystemProfile) -> tuple[list[UpdateCandidate], list[str]]:
        raise NotImplementedError
