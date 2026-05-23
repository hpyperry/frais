from __future__ import annotations

import logging
from pathlib import Path

from rich.console import Console

from .paths import DEFAULT_LOG_FILE, LOG_MAX_SIZE

_stderr_console = Console(stderr=True)


def configure_logging(verbose: bool, debug: bool, log_file: str | None, no_log: bool) -> None:
    file_level = logging.DEBUG if debug else logging.INFO if verbose else logging.WARNING
    stderr_level = logging.DEBUG if debug else logging.INFO if verbose else logging.ERROR

    stderr_handler = logging.StreamHandler()
    stderr_handler.setLevel(stderr_level)

    handlers: list[logging.Handler] = [stderr_handler]

    if not no_log:
        path = Path(log_file) if log_file else DEFAULT_LOG_FILE
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size > LOG_MAX_SIZE:
                path.write_text("")
            file_handler = logging.FileHandler(str(path), encoding="utf-8")
            file_handler.setLevel(file_level)
            handlers.append(file_handler)
        except OSError as exc:
            _stderr_console.print(f"[yellow]Warning: could not open log file {path}: {exc}[/yellow]")

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=handlers,
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.INFO if debug else logging.WARNING)
    for logger_name in ("httpcore", "urllib3", "ddgs", "primp"):
        logging.getLogger(logger_name).setLevel(logging.INFO)
