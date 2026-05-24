"""Shared signal handling for interruptible commands."""

import os
import signal
from typing import Any


def install_interrupt_handler() -> Any:
    """Install a SIGINT handler that cleans up the terminal and exits.

    Returns the original handler for later restoration.
    Handles the Rich progress-bar context that can swallow ANSI escape writes.
    """
    def _on_interrupt(signum: int, frame: object) -> None:
        try:
            os.write(1, b"\033[?25h\n")
        except OSError:
            pass
        try:
            os.killpg(os.getpgrp(), signal.SIGTERM)
        except OSError:
            pass
        os._exit(130)

    return signal.signal(signal.SIGINT, _on_interrupt)
