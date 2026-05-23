from __future__ import annotations

from dataclasses import dataclass

from .models import ScanResult
from .store.ignore_store import load_ignored


@dataclass(slots=True)
class IgnoreFilterResult:
    scan_result: ScanResult
    ignored_count: int


def apply_ignore_filter(scan_result: ScanResult) -> IgnoreFilterResult:
    ignored_ids = load_ignored()
    ignored_count = 0
    if not ignored_ids:
        return IgnoreFilterResult(scan_result=scan_result, ignored_count=ignored_count)

    for plugin_result in scan_result.plugin_results.values():
        plugin_result.items = [item for item in plugin_result.items if item.id not in ignored_ids]
        before_count = len(plugin_result.candidates)
        plugin_result.candidates = [
            candidate for candidate in plugin_result.candidates
            if candidate.item.id not in ignored_ids
        ]
        ignored_count += before_count - len(plugin_result.candidates)

    return IgnoreFilterResult(scan_result=scan_result, ignored_count=ignored_count)
