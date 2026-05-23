from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


def run_json(command: list[str], ok_codes: tuple[int, ...] = (0,), timeout: int = 60) -> dict[str, Any]:
    """Run a command with isolated env and parse stdout as JSON."""
    logger.debug("run_json command=%s", " ".join(command))
    env = os.environ.copy()
    env.pop("DYLD_LIBRARY_PATH", None)
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Command timed out after {timeout}s: {' '.join(command)}") from exc
    logger.debug(
        "run_json returncode=%s stdout_bytes=%d stderr_bytes=%d",
        result.returncode,
        len(result.stdout),
        len(result.stderr),
    )
    if result.returncode not in ok_codes:
        message = result.stderr.strip() or f"Command failed (exit {result.returncode}): {' '.join(command)}"
        raise RuntimeError(message)
    if not result.stdout.strip():
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON from {' '.join(command)}") from exc
