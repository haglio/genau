"""The 40 ms grid the trace reads the playhead on.

:mod:`nau.drive_trace` snaps the playhead onto it before it finds the turn in
play, so the stable picture slides under a fixed set of knots at the cadence
Genau's own publishes repaint at.  :mod:`nau.status` snaps the same way before
it looks up what the trace chose: read raw, the status crossed a boundary up to
a quantum before the trace did and asked for a choice the trace had not made
yet, and the published field went empty for a frame.  One grid, read by both,
so the two name the same turn on every frame.

Kept free of every other module so :mod:`nau.status` can read it without the
trace's machinery, and player_core behind it, coming along.
"""
from __future__ import annotations

SLIDE_QUANTUM_MS = 40


def on_the_grid(position_ms: int) -> int:
    """*position_ms* snapped down onto the grid."""
    return position_ms - position_ms % SLIDE_QUANTUM_MS
