from __future__ import annotations

import argparse
import logging
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


def consume_command_file(
    path: Path, *, logger: logging.Logger | None = None, uppercase: bool = True
) -> list[str]:
    try:
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8").replace("\ufeff", "").strip()
        if uppercase:
            text = text.upper()
        if not text:
            return []
        path.write_text("", encoding="utf-8")
        return [line.strip() for line in text.splitlines() if line.strip()]
    except Exception:
        if logger is not None:
            logger.exception("Failed to consume command file %s", path)
        return []


def read_paused_state(path: Path, *, logger: logging.Logger | None = None) -> bool:
    try:
        if not path.exists():
            return False
        return path.read_text(encoding="utf-8").replace("\ufeff", "").strip() == "1"
    except Exception:
        if logger is not None:
            logger.exception("Failed to read paused state file %s", path)
        return False


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
