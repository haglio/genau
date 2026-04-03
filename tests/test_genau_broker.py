"""Tests for genau.broker."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from genau.broker import BROKER_PROCESS_PATTERN, is_broker_running, ensure_broker_running


def test_broker_process_pattern_matches_broker_app():
    import re
    assert re.search(BROKER_PROCESS_PATTERN, "python -m fun_time.broker_app --config foo.json")


def test_is_broker_running_returns_true_when_powershell_finds_process():
    fake_result = type("R", (), {"returncode": 0, "stdout": "RUNNING\n"})()
    with patch("genau.broker.subprocess.run", return_value=fake_result):
        assert is_broker_running() is True


def test_is_broker_running_returns_false_when_no_process():
    fake_result = type("R", (), {"returncode": 0, "stdout": ""})()
    with patch("genau.broker.subprocess.run", return_value=fake_result):
        assert is_broker_running() is False


def test_ensure_broker_starts_tray_when_not_running(tmp_path: Path):
    launched = []
    fake_result = type("R", (), {"returncode": 0, "stdout": ""})()

    def fake_run(*args, **kwargs):
        return fake_result

    def fake_popen(*args, **kwargs):
        launched.append(args[0])
        return type("P", (), {"pid": 123})()

    tray_vbs = tmp_path / "launch_broker_tray.vbs"
    tray_vbs.touch()

    with patch("genau.broker.subprocess.run", side_effect=fake_run), \
         patch("genau.broker.subprocess.Popen", side_effect=fake_popen):
        ensure_broker_running(tray_vbs)

    assert len(launched) == 1
    assert "wscript.exe" in launched[0][0]


def test_ensure_broker_skips_launch_when_already_running(tmp_path: Path):
    launched = []
    fake_result = type("R", (), {"returncode": 0, "stdout": "RUNNING\n"})()

    with patch("genau.broker.subprocess.run", return_value=fake_result):
        ensure_broker_running(tmp_path / "dummy.vbs")

    assert launched == []
