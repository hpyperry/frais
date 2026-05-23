from __future__ import annotations

import json
import logging
from pathlib import Path

from ..models import ScanResult

logger = logging.getLogger(__name__)


def save_scan_cache(scan_result: ScanResult, path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(scan_result.to_dict(), ensure_ascii=False, indent=2))
        tmp_path.replace(path)
    except OSError as exc:
        logger.warning("failed to save scan cache: %s", exc)
