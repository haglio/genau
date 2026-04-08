"""Tests for genau.runtime_support."""
from __future__ import annotations

from pathlib import Path

from genau.runtime_support import consume_command_file


def test_consume_returns_empty_list_when_file_missing(tmp_path: Path):
    path = tmp_path / "cmd.txt"

    result = consume_command_file(path)

    assert result == []


def test_consume_returns_empty_list_when_file_empty(tmp_path: Path):
    path = tmp_path / "cmd.txt"
    path.write_text("", encoding="utf-8")

    result = consume_command_file(path)

    assert result == []


def test_consume_returns_single_command(tmp_path: Path):
    path = tmp_path / "cmd.txt"
    path.write_text("NEXT", encoding="utf-8")

    result = consume_command_file(path)

    assert result == ["NEXT"]


def test_consume_returns_multiple_commands_from_multiline(tmp_path: Path):
    path = tmp_path / "cmd.txt"
    path.write_text("RESUME\nHUD_ON", encoding="utf-8")

    result = consume_command_file(path)

    assert result == ["RESUME", "HUD_ON"]


def test_consume_skips_blank_lines(tmp_path: Path):
    path = tmp_path / "cmd.txt"
    path.write_text("RESUME\n\nHUD_ON\n", encoding="utf-8")

    result = consume_command_file(path)

    assert result == ["RESUME", "HUD_ON"]


def test_consume_clears_file_after_reading(tmp_path: Path):
    path = tmp_path / "cmd.txt"
    path.write_text("NEXT", encoding="utf-8")

    consume_command_file(path)

    assert path.read_text(encoding="utf-8") == ""


def test_consume_uppercases_commands(tmp_path: Path):
    path = tmp_path / "cmd.txt"
    path.write_text("resume\nhud_on", encoding="utf-8")

    result = consume_command_file(path)

    assert result == ["RESUME", "HUD_ON"]
