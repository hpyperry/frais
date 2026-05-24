from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "scripts" / "frais_entry.py"
DIST_BINARY = ROOT / "dist" / "frais"


def main() -> None:
    if shutil.which("pyinstaller") is None:
        raise SystemExit("pyinstaller is missing. Run with `uv run --extra build python scripts/build_binary.py`.")

    # Build wheel so .dist-info with entry_points exists for PyInstaller
    subprocess.run(["uv", "build"], cwd=ROOT, check=True)
    wheels = sorted(ROOT.glob("dist/frais-*.whl"))
    if wheels:
        subprocess.run(["uv", "pip", "install", "--reinstall", str(wheels[-1])], cwd=ROOT, check=True)

    subprocess.run(
        [
            "pyinstaller",
            "--onedir",
            "--noupx",
            "--name",
            "frais",
            "--clean",
            "--copy-metadata",
            "frais",
            "--additional-hooks-dir",
            str(ROOT / "scripts"),
            str(ENTRYPOINT),
        ],
        cwd=ROOT,
        check=True,
    )
    print(f"Built binary: {DIST_BINARY}")


if __name__ == "__main__":
    main()
