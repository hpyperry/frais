from __future__ import annotations

from pathlib import Path

DEFAULT_LOG_DIR = Path.home() / ".frais" / "log"
DEFAULT_LOG_FILE = DEFAULT_LOG_DIR / "frais.log"
DEFAULT_ERROR_LOG_FILE = DEFAULT_LOG_DIR / "error.log"
ADVICE_CACHE = DEFAULT_LOG_DIR / "last_advice.json"
LOG_MAX_SIZE = 50 * 1024 * 1024
