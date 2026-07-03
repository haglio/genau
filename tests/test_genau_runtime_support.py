"""Tests for genau.runtime_support."""
from __future__ import annotations

from pathlib import Path

from genau.runtime_support import (
    broker_cmd_file_for_mode,
    consume_command_file,
    read_paused_state,
)


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


def test_consume_preserves_case_when_uppercase_disabled(tmp_path: Path):
    cmd_file = tmp_path / "cmd.txt"
    cmd_file.write_text("PLAY_FILE C:/Videos/MyClip.mp4\n", encoding="utf-8")

    commands = consume_command_file(cmd_file, uppercase=False)

    assert commands == ["PLAY_FILE C:/Videos/MyClip.mp4"]


def test_broker_cmd_file_for_mode_standalone_returns_path(tmp_path: Path):
    # Standalone Genau self-parks the OSR2 via the broker, so it keeps its file.
    path = tmp_path / "broker_cmd.txt"

    assert broker_cmd_file_for_mode(path, fun_time=False) == path


def test_broker_cmd_file_for_mode_fun_time_returns_none(tmp_path: Path):
    # Under Fun Time the orchestrator owns the OSR2 handoff; Genau must not write
    # the broker file, or its PARK-on-pause clobbers the orchestrator's RESUME.
    path = tmp_path / "broker_cmd.txt"

    assert broker_cmd_file_for_mode(path, fun_time=True) is None


def test_read_paused_state_reads_flag(tmp_path: Path):
    paused_file = tmp_path / "paused.txt"

    assert read_paused_state(paused_file) is False

    paused_file.write_text("1", encoding="utf-8")
    assert read_paused_state(paused_file) is True

    paused_file.write_text("0", encoding="utf-8")
    assert read_paused_state(paused_file) is False
