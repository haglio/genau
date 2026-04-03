"""Broker detection and startup for standalone Genau operation."""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from .runtime_support import hidden_subprocess_kwargs

BROKER_PROCESS_PATTERN = r"fun_time\.broker_app"

_log = logging.getLogger(__name__)


def is_broker_running() -> bool:
    if sys.platform != "win32":
        return False
    command = [
        "powershell.exe",
        "-NoProfile",
        "-Command",
        (
            "$proc = Get-CimInstance Win32_Process | Where-Object { "
            "$_.Name -match '^pythonw?\\.exe$|^py\\.exe$' -and "
            "$_.CommandLine -match '" + BROKER_PROCESS_PATTERN + "' "
            "} | Select-Object -First 1; "
            "if ($null -ne $proc) { 'RUNNING' }"
        ),
    ]
    result = subprocess.run(
        command, capture_output=True, text=True, check=False,
        **hidden_subprocess_kwargs(),
    )
    return result.returncode == 0 and "RUNNING" in result.stdout


def ensure_broker_running(tray_launcher: Path) -> bool:
    if is_broker_running():
        _log.info("Broker is already running")
        return True

    if not tray_launcher.exists():
        _log.warning("Broker tray launcher not found: %s", tray_launcher)
        return False

    _log.warning("Broker not running; starting %s", tray_launcher)
    subprocess.Popen(
        ["wscript.exe", str(tray_launcher)],
        cwd=str(tray_launcher.parent),
        **hidden_subprocess_kwargs(),
    )
    return True
