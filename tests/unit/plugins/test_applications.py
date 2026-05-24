from __future__ import annotations

import plistlib
from pathlib import Path

from frais.models import SourceKind
from frais.plugins.applications import classify_source, scan_applications


def test_scan_application_plist(tmp_path: Path) -> None:
    app = tmp_path / "Demo.app"
    contents = app / "Contents"
    contents.mkdir(parents=True)
    with (contents / "Info.plist").open("wb") as handle:
        plistlib.dump(
            {
                "CFBundleIdentifier": "com.example.demo",
                "CFBundleName": "Demo",
                "CFBundleShortVersionString": "1.2.3",
            },
            handle,
        )

    items = scan_applications([str(tmp_path)])

    assert len(items) == 1
    assert items[0].id == "com.example.demo"
    assert items[0].name == "Demo"
    assert items[0].current_version == "1.2.3"


def test_local_build_classification() -> None:
    source = classify_source(
        "com.example.local",
        {"authority": "adhoc", "team_id": None},
        None,
    )

    assert source == SourceKind.LOCAL_BUILD
