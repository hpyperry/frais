from __future__ import annotations

import platform
from pathlib import Path

from .models import SystemProfile


def detect_system() -> SystemProfile:
    os_name = platform.system() or "Unknown"
    os_version = platform.mac_ver()[0] if os_name == "Darwin" else platform.release()
    applications_paths = ["/Applications", str(Path.home() / "Applications")]
    return SystemProfile(
        os_name="macOS" if os_name == "Darwin" else os_name,
        os_version=os_version or "unknown",
        arch=platform.machine() or "unknown",
        applications_paths=applications_paths,
    )
