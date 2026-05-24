from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rich.console import Console

from .paths import DEFAULT_ERROR_LOG_FILE, DEFAULT_LOG_FILE, LOG_MAX_SIZE

_stderr_console = Console(stderr=True)

LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-5s [%(name)s] %(filename)s:%(lineno)d %(funcName)s() — %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_BACKUP_COUNT = 2


def _ensure_log_dir(path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        return True
    except OSError as exc:
        _stderr_console.print(f"[yellow]Warning: could not create log directory {path.parent}: {exc}[/yellow]")
        return False


def _add_file_handler(
    handlers: list[logging.Handler],
    path: Path,
    level: int,
    backup_count: int = _BACKUP_COUNT,
) -> None:
    if not _ensure_log_dir(path):
        return
    try:
        handler = RotatingFileHandler(
            str(path),
            encoding="utf-8",
            maxBytes=LOG_MAX_SIZE,
            backupCount=backup_count,
        )
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
        handlers.append(handler)
    except OSError as exc:
        _stderr_console.print(f"[yellow]Warning: could not open log file {path}: {exc}[/yellow]")


def configure_logging(debug: bool, log_file: str | None, no_log: bool) -> None:
    file_level = logging.DEBUG if debug else logging.INFO

    handlers: list[logging.Handler] = []

    if not no_log:
        root_log_path = Path(log_file) if log_file else DEFAULT_LOG_FILE
        error_log_path = Path(log_file).parent / "error.log" if log_file else DEFAULT_ERROR_LOG_FILE

        _add_file_handler(handlers, root_log_path, file_level, backup_count=2)
        _add_file_handler(handlers, error_log_path, logging.ERROR, backup_count=1)

    logging.basicConfig(
        level=file_level,
        handlers=handlers,
        force=True,
    )
    logging.getLogger("frais").setLevel(logging.DEBUG if debug else logging.INFO)
