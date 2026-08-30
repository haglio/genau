"""Who owns the OSR2 when Genau runs under Fun Time."""
from __future__ import annotations

from pathlib import Path


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
