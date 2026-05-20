from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class SourceKind(StrEnum):
    APPLICATION = "application"
    LOCAL_BUILD = "local build"
    NETWORK_DOWNLOAD = "network download"
    APP_STORE = "app store"
    HOMEBREW_FORMULA = "brew"
    HOMEBREW_CASK = "brew cask"
    NPM_GLOBAL = "npm"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class SystemProfile:
    os_name: str
    os_version: str
    arch: str
    applications_paths: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LLMConfig:
    provider: str
    base_url: str | None
    model: str | None
    api_key_source: str | None
    has_api_key: bool
    api_key_suffix: str | None = None

    @property
    def is_ready(self) -> bool:
        return bool(self.has_api_key and self.base_url and self.model)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "api_key_source": self.api_key_source,
            "has_api_key": self.has_api_key,
            "api_key": f"***{self.api_key_suffix}" if self.api_key_suffix else None,
            "ready": self.is_ready,
        }


@dataclass(slots=True)
class SoftwareItem:
    id: str
    name: str
    kind: str
    source: SourceKind
    current_version: str | None
    path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source"] = self.source.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SoftwareItem:
        return cls(
            id=data["id"],
            name=data["name"],
            kind=data.get("kind", "application"),
            source=SourceKind(data.get("source", "unknown")),
            current_version=data.get("current_version"),
            path=data.get("path"),
            metadata=data.get("metadata", {}),
        )


@dataclass(slots=True)
class ResearchResult:
    latest_version: str | None = None
    release_notes_url: str | None = None
    download_url: str | None = None
    source_repo_url: str | None = None
    confidence: str = "unknown"
    evidence: list[str] = field(default_factory=list)
    release_notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DependencyImpact:
    used_by: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    impact_level: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DependencyImpact:
        return cls(
            used_by=data.get("used_by", []),
            depends_on=data.get("depends_on", []),
            impact_level=data.get("impact_level", "unknown"),
        )


@dataclass(slots=True)
class UpdateCandidate:
    item: SoftwareItem
    latest_version: str | None = None
    release_notes: str | None = None
    dependency_impact: DependencyImpact = field(default_factory=DependencyImpact)
    risk_level: str = "unknown"
    ai_summary: str | None = None
    recommended_action: str = "No action"
    can_auto_update: bool = False
    command: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["item"] = self.item.to_dict()
        data["dependency_impact"] = self.dependency_impact.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UpdateCandidate:
        return cls(
            item=SoftwareItem.from_dict(data["item"]),
            latest_version=data.get("latest_version"),
            release_notes=data.get("release_notes"),
            dependency_impact=DependencyImpact.from_dict(data.get("dependency_impact", {})),
            risk_level=data.get("risk_level", "unknown"),
            ai_summary=data.get("ai_summary"),
            recommended_action=data.get("recommended_action", "No action"),
            can_auto_update=data.get("can_auto_update", False),
            command=data.get("command", []),
            evidence=data.get("evidence", []),
        )


@dataclass(slots=True)
class ScanResult:
    system: SystemProfile
    applications: list[SoftwareItem] = field(default_factory=list)
    candidates: list[UpdateCandidate] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "system": self.system.to_dict(),
            "applications": [item.to_dict() for item in self.applications],
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "skipped": self.skipped,
        }
