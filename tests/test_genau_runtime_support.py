"""Tests for genau.runtime_support.

The command/paused file channel these used to sit beside is now
player_core.file_channel, and is covered by that repo's suite.
"""
from __future__ import annotations

from pathlib import Path

from genau.runtime_support import broker_cmd_file_for_mode


def test_broker_cmd_file_for_mode_standalone_returns_path(tmp_path: Path):
    # Standalone Genau self-parks the OSR2 via the broker, so it keeps its file.
    path = tmp_path / "broker_cmd.txt"

    assert broker_cmd_file_for_mode(path, fun_time=False) == path


def test_broker_cmd_file_for_mode_fun_time_returns_none(tmp_path: Path):
    # Under Fun Time the orchestrator owns the OSR2 handoff; Genau must not write
    # the broker file, or its PARK-on-pause clobbers the orchestrator's RESUME.
    path = tmp_path / "broker_cmd.txt"

    assert broker_cmd_file_for_mode(path, fun_time=True) is None
