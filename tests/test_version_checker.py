from __future__ import annotations

import httpx
import pytest

from frais.models import SoftwareItem, SourceKind
from frais.version_checker import check_app_store_version


def test_returns_none_for_non_app_store() -> None:
    item = SoftwareItem(id="com.example.app", name="App", kind="application", source=SourceKind.APPLICATION, current_version="1.0")
    version, track_id = check_app_store_version(item)
    assert version is None
    assert track_id is None


def test_returns_none_for_invalid_bundle_id() -> None:
    item = SoftwareItem(id="no-dot", name="App", kind="application", source=SourceKind.APP_STORE, current_version="1.0")
    version, track_id = check_app_store_version(item)
    assert version is None
    assert track_id is None


def test_returns_none_for_empty_bundle_id() -> None:
    item = SoftwareItem(id="", name="App", kind="application", source=SourceKind.APP_STORE, current_version="1.0")
    version, track_id = check_app_store_version(item)
    assert version is None
    assert track_id is None


def test_returns_version_and_track_id(monkeypatch) -> None:
    resp = httpx.Response(200, json={"resultCount": 1, "results": [{"version": "2.0", "trackId": 12345}]}, request=httpx.Request("GET", "https://itunes.apple.com/lookup"))
    monkeypatch.setattr(httpx, "get", lambda url, **kw: resp)
    item = SoftwareItem(id="com.example.app", name="App", kind="application", source=SourceKind.APP_STORE, current_version="1.0")
    version, track_id = check_app_store_version(item)
    assert version == "2.0"
    assert track_id == 12345


def test_returns_none_when_no_results(monkeypatch) -> None:
    resp = httpx.Response(200, json={"resultCount": 0}, request=httpx.Request("GET", "https://itunes.apple.com/lookup"))
    monkeypatch.setattr(httpx, "get", lambda url, **kw: resp)
    item = SoftwareItem(id="com.example.app", name="App", kind="application", source=SourceKind.APP_STORE, current_version="1.0")
    version, track_id = check_app_store_version(item)
    assert version is None
    assert track_id is None


def test_returns_none_when_no_version_in_result(monkeypatch) -> None:
    resp = httpx.Response(200, json={"resultCount": 1, "results": [{"trackId": 12345}]}, request=httpx.Request("GET", "https://itunes.apple.com/lookup"))
    monkeypatch.setattr(httpx, "get", lambda url, **kw: resp)
    item = SoftwareItem(id="com.example.app", name="App", kind="application", source=SourceKind.APP_STORE, current_version="1.0")
    version, track_id = check_app_store_version(item)
    assert version is None
    assert track_id is None


def test_returns_none_on_http_error(monkeypatch) -> None:
    def raise_error(url, **kw):
        raise Exception("network error")
    monkeypatch.setattr(httpx, "get", raise_error)
    item = SoftwareItem(id="com.example.app", name="App", kind="application", source=SourceKind.APP_STORE, current_version="1.0")
    version, track_id = check_app_store_version(item)
    assert version is None
    assert track_id is None
