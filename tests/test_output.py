from __future__ import annotations

import json

import typer

import pytest

from frais.commands._output import exit_with_error, print_json_success


def test_print_json_success_outputs_valid_json(capsys) -> None:
    print_json_success()
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data == {"ok": True}


def test_print_json_success_includes_ok_true(capsys) -> None:
    print_json_success(foo="bar", num=42)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is True
    assert data["foo"] == "bar"
    assert data["num"] == 42


def test_print_json_success_nested_dict(capsys) -> None:
    print_json_success(items=[{"a": 1}, {"b": 2}], total=2)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is True
    assert data["items"] == [{"a": 1}, {"b": 2}]
    assert data["total"] == 2


def test_print_json_success_ok_cannot_be_overridden(capsys) -> None:
    print_json_success(ok=False, foo="bar")
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is True  # caller cannot override
    assert data["foo"] == "bar"


def test_exit_with_error_json_mode_outputs_valid_json(capsys) -> None:
    with pytest.raises(typer.Exit) as exc_info:
        exit_with_error("something went wrong", json_mode=True)
    assert exc_info.value.exit_code == 1
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data == {"ok": False, "error": "something went wrong"}


def test_exit_with_error_json_mode_custom_exit_code(capsys) -> None:
    with pytest.raises(typer.Exit) as exc_info:
        exit_with_error("not found", json_mode=True, exit_code=2)
    assert exc_info.value.exit_code == 2


def test_exit_with_error_cli_mode_prints_red(capsys) -> None:
    with pytest.raises(typer.Exit):
        exit_with_error("something went wrong", json_mode=False)
    captured = capsys.readouterr()
    assert "Error:" in captured.err
    assert "something went wrong" in captured.err


def test_exit_with_error_cli_mode_default_exit_code(capsys) -> None:
    with pytest.raises(typer.Exit) as exc_info:
        exit_with_error("fail", json_mode=False)
    assert exc_info.value.exit_code == 1
