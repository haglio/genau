"""What Nau publishes in its status file for the Fun Time orchestrator.

The dispatch side reads these to drive clipper_save, the dashboard funscript
highlight, and the record-button state.  The throttled writing itself is
:class:`player_core.status.StatusWriter`; this module is only the field set,
because these keys and their order are Nau's own contract with fun_time — no
other player publishes them.
"""
from __future__ import annotations


def status_fields(session) -> dict[str, str]:
    return {
        "video": str(session.current_video),
        "position_ms": str(int(session.position_ms)),
        "duration_ms": str(int(session.duration_ms)),
        "has_funscript": "1" if session.has_funscript else "0",
        "funscript_resting": "1" if session.funscript_resting else "0",
        "state": str(session.loop_state),
        "paused": "1" if session.is_paused else "0",
        # Whether the video repeats rather than ending.  Nau's own state, but the
        # console that draws its lock is drawn by whoever holds the primary slot —
        # Genau in genau mode, which has no such lock to ask — so it goes out here
        # and comes back down on the console panel, the way the loop state does.
        "locked": "1" if session.locked else "0",
    }
