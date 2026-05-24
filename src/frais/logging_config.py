from __future__ import annotations

import logging
from pathlib import Path

from rich.console import Console

from .paths import DEFAULT_ERROR_LOG_FILE, DEFAULT_LOG_FILE, LOG_MAX_SIZE

_stderr_console = Console(stderr=True)

LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-5s [%(name)s] %(filename)s:%(lineno)d %(funcName)s() — %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _rotate_log(path: Path) -> None:
    """Clear log file if it exceeds max size."""
    if path.exists() and path.stat().st_size > LOG_MAX_SIZE:
        path.write_text("")


def _ensure_log_dir(path: Path) -> bool:
    """Create parent directories for a log file. Returns False on failure."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        return True
    except OSError as exc:
        _stderr_console.print(f"[yellow]Warning: could not create log directory {path.parent}: {exc}[/yellow]")
        return False


def _add_file_handler(handlers: list[logging.Handler], path: Path, level: int) -> None:
    """Create and add a FileHandler for the given path and level."""
    if not _ensure_log_dir(path):
        return
    _rotate_log(path)
    try:
        handler = logging.FileHandler(str(path), encoding="utf-8")
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
        handlers.append(handler)
    except OSError as exc:
        _stderr_console.print(f"[yellow]Warning: could not open log file {path}: {exc}[/yellow]")


def configure_logging(verbose: bool, debug: bool, log_file: str | None, no_log: bool) -> None:
    file_level = logging.DEBUG if debug else logging.INFO if verbose else logging.WARNING
    stderr_level = logging.DEBUG if debug else logging.INFO if verbose else logging.ERROR

    stderr_handler = logging.StreamHandler()
    stderr_handler.setLevel(stderr_level)
    stderr_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))

    handlers: list[logging.Handler] = [stderr_handler]

    if not no_log:
        root_log_path = Path(log_file) if log_file else DEFAULT_LOG_FILE
        error_log_path = Path(log_file).parent / "error.log" if log_file else DEFAULT_ERROR_LOG_FILE

        _add_file_handler(handlers, root_log_path, file_level)
        _add_file_handler(handlers, error_log_path, logging.ERROR)

    logging.basicConfig(
        level=logging.DEBUG,
        handlers=handlers,
        force=True,
    )
    third_party_level = logging.INFO if debug else logging.WARNING
    logging.getLogger("httpx").setLevel(third_party_level)
    for logger_name in ("httpcore", "urllib3", "ddgs", "primp"):
        logging.getLogger(logger_name).setLevel(third_party_level)
