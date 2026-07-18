"""Odds and ends the apps in this repo share.

The command/paused file channel that used to live here is now
:mod:`player_core.file_channel` — Fun Time drives its satellites through the
same protocol, so it belongs to the player core rather than to Genau.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def preparse_config_path(argv: list[str] | None) -> str | None:
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--config")
    known, _ = ap.parse_known_args(argv)
    return known.config


def broker_cmd_file_for_mode(broker_cmd_file: Path, *, fun_time: bool) -> Path | None:
    """Return the broker command file Genau may write, or None if it must not.

    Standalone Genau self-manages the OSR2 through the broker: it writes PARK when
    it pauses and RESUME when it resumes. Under Fun Time the orchestrator owns that
    handoff instead — when a mode switch leaves a Genau-active mode it hands the
    OSR2 to MultiFunPlayer by writing RESUME to the broker. If Genau also wrote its
    own PARK on the same pause it would clobber that RESUME and strand the device
    away from MFP, so under Fun Time Genau writes nothing to the broker.
    """
    return None if fun_time else broker_cmd_file


def hidden_subprocess_kwargs() -> dict[str, Any]:
    if os.name != "nt" and sys.platform != "win32":
        return {}

    kwargs: dict[str, Any] = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    kwargs["startupinfo"] = startupinfo
    show_window = getattr(subprocess, "SW_HIDE", None)
    if show_window is not None:
        startupinfo.wShowWindow = show_window
    return kwargs
