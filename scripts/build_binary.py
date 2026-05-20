from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "scripts" / "checkupgrade_entry.py"
DIST_BINARY = ROOT / "dist" / "checkupgrade"


def main() -> None:
    if shutil.which("pyinstaller") is None:
        raise SystemExit("pyinstaller is missing. Run with `uv run --extra build python scripts/build_binary.py`.")
    subprocess.run(
        [
            "pyinstaller",
            "--onefile",
            "--name",
            "checkupgrade",
            "--clean",
            str(ENTRYPOINT),
        ],
        cwd=ROOT,
        check=True,
    )
    print(f"Built binary: {DIST_BINARY}")


if __name__ == "__main__":
    main()
