"""What Nau publishes in its status file for the Fun Time orchestrator.

The dispatch side reads these to drive clipper_save, the dashboard funscript
highlight, and the record-button state.  The throttled writing itself is
:class:`player_core.status.StatusWriter`; here are the whole field set and the
one choice that goes into it (:func:`next_handoff_touch`), because these keys
and their order are Nau's own contract with fun_time — no other player
publishes them.
"""
from __future__ import annotations


def next_handoff_touch(script, position_ms: int, descent_tops: dict) -> int | None:
    """The touch-down the trace has chosen for the boundary ahead (or the one
    just crossed), in media ms — None when there is none (a raised floor, no
    script, nothing latched yet).

    Published so the arbiter can END Genau's turn exactly where the picture
    drew the blue ending.  When each side chose its own touch from its own read
    of the wave, they could pick different troughs — the arbiter stopped the
    device one touch early, and the leftover drawn blue vanished the moment
    the dot reached it.  One chooser, the picture; the arbiter follows it.
    """
    if script is None:
        return None
    if script.is_resting_at(position_ms):
        _, boundary = script.turn_bounds_at(position_ms)
    else:
        boundary, _ = script.turn_bounds_at(position_ms)
    if boundary is None:
        return None
    entry = descent_tops.get(boundary)
    if entry is None:
        return None
    return entry[2]


def status_fields(session, handoff_touch_ms: int | None) -> dict[str, str]:
    """Everything Nau publishes about itself, in the order it is written.

    *handoff_touch_ms* is the touch-down the trace has chosen for the boundary
    in play (:func:`next_handoff_touch` answers it out of the latch
    :class:`nau.drive_gate.DriveGate` holds), and None where there is none.  It
    is asked for rather than defaulted because a caller that forgot it would
    publish an empty field on every tick, and the arbiter would go on ending
    Genau's turn wherever its own read of the wave put it.
    """
    loop_in_ms, loop_out_ms = session.loop_bounds or (0, 0)
    return {
        "video": str(session.current_video),
        "position_ms": str(int(session.position_ms)),
        "duration_ms": str(int(session.duration_ms)),
        "has_funscript": "1" if session.has_funscript else "0",
        "funscript_resting": "1" if session.funscript_resting else "0",
        "state": str(session.loop_state),
        # The A/B range a running loop holds, and 0/0 for no loop.  Everything
        # else about this player survives a restart in a file something rebuilds
        # it from — the playlist, the flags fun_time seeds — but a loop is a
        # range inside one video and lives nowhere but here, so a session that
        # never published it could never be handed it back.
        "loop_in_ms": str(int(loop_in_ms)),
        "loop_out_ms": str(int(loop_out_ms)),
        "paused": "1" if session.is_paused else "0",
        # Whether the video repeats rather than ending.  Nau's own state, but the
        # console that draws its lock is drawn by whoever holds the main slot —
        # Genau in genau mode, which has no such lock to ask — so it goes out here
        # and comes back down on the console panel, the way the loop state does.
        "locked": "1" if session.locked else "0",
        # Where the picture drew Genau's turn ending.  Empty rather than zero
        # when the trace has chosen none: zero is a real media time, and the
        # arbiter reading one would end the turn at the top of the video.
        "handoff_touch_ms": "" if handoff_touch_ms is None else str(int(handoff_touch_ms)),
    }
