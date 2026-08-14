"""What the device is about to be asked to do, and by whom — the trace's model.

The line is four things in a row, and nothing else:

    whatever Genau is doing
    a ramp from where that leaves the device down onto the park
    whatever the funscript is doing
    a ramp back up to where Genau's stroke begins

Green is the script scripting, blue is Genau stroking, grey is a ramp or the
rest between them — nobody drives through those, the device is being handed
over.

Every boundary here is a *time the script fixes*: a script turn opens
QUIET_LEAD_IN_MS before its cluster and closes QUIET_LEAD_OUT_MS after it, and
the funscript does not change while it plays.  So the whole picture is a
function of the playhead, computed the same way on every frame, and it slides
without changing shape.

It used to end Genau's turn on the stroke's next floor-touch instead — a moment
only the live stroke knew, recomputed every frame from a window that advances
under it.  That answer moved: the final cycle flickered in and out as the trough
crossed the tolerance, and vanished outright the moment Genau paused and its
published stroke froze at the floor.  Nothing here asks the stroke *when*
anything happens any more; the stroke is only ever asked *what height*.

The one thing the trace cannot recompute is the height Genau let go at, because
once it is paused its published stroke no longer says where the device was.  So
the caller records that one number at the handoff and passes it back in.

Kept out of :mod:`nau.app` and free of Pillow, like :mod:`nau.console` is, so the
shape of the picture is testable without a window or a font.
"""
from __future__ import annotations

from dataclasses import replace

from player_core.funscript import HANDOFF_RAMP_MS

from player_core.drive_readout import (
    DRIVEN_BY_FUNSCRIPT,
    DRIVEN_BY_GENAU,
    DRIVEN_BY_NEUTRAL,
    DRIVEN_BY_NOTHING,
    POSITION_MAX,
    TRACE_SAMPLES,
    DriveHud,
    stroke_floor,
)

# The window into the script slides continuously, so read at the raw playhead it
# would move — and repaint the console — at Nau's full frame rate.  Quantized to
# the cadence Genau's own publishes already repaint at while the stroke scrolls,
# the green moves exactly as smoothly as the blue, for the same cost.
_SLIDE_QUANTUM_MS = 40


def drive_readout(
    published: DriveHud | None,
    *,
    script,
    position_ms: int,
    speed: float = 1.0,
    genau_behind: bool,
    osr2_has_script: bool,
    let_go_at: tuple[int, float] | None = None,
) -> DriveHud:
    """The readout to draw, folding the funscript's own shape into it.

    *published* is Genau's readout as it last said it, or None where there is no
    Genau behind the screen (Nau's own mode).  *genau_behind* says whether Genau
    is there to take the gaps, and *osr2_has_script* whether a script has the
    device now — which decides only where the position marker comes from.

    *let_go_at* is ``(playhead, height)`` for the last time Genau handed the
    device over: the one fact the picture cannot recompute, because a paused
    Genau publishes the stroke it will resume with rather than the position it
    stopped at.  Before that handoff the same height is read off the stroke
    itself, so the ramp is drawn the same way either side of the moment.

    The span is Genau's own — it publishes the number with its trace — scaled by
    the playback rate, because the trace covers wall-clock time and at double
    speed twice as much of the script goes past in it.
    """
    base = published or DriveHud()
    if script is None:
        return base
    position_ms -= position_ms % _SLIDE_QUANTUM_MS
    span_ms = round(base.trace_seconds * 1000 * speed)
    step = span_ms / max(1, TRACE_SAMPLES - 1)
    # The device's *plan*, not the script's interpolated line: through the quiet
    # the driver rests the device at its park and rises only to meet the next
    # cluster, and a green line that held the last position across those
    # stretches was a picture the device visibly contradicted.  The window sits
    # on whole knots — the script never changes while it plays, so its picture is
    # computed once and only reread — and the leftover fraction of a knot rides
    # along as ``slide`` for the painter to shift the stable shape by.
    scripted, slide = script.planned_trace_window(position_ms, span_ms, TRACE_SAMPLES)
    if len(scripted) != TRACE_SAMPLES + 1:
        return base
    # Sample times anchored to the window's own knots, so what each sample says
    # never depends on where inside a knot the playhead sits.
    anchor_ms = position_ms - slide * step
    stroke = base.waveform if len(base.waveform) == TRACE_SAMPLES else None
    if not genau_behind:
        stroke = None
    # Where the stroke bottoms out: where the climb is headed, and where the
    # waiting stroke opens.
    floor_height = stroke_floor(base.center, base.amplitude) if stroke else 0.0

    def stroke_at(index: float) -> float:
        return stroke[min(max(round(index), 0), TRACE_SAMPLES - 1)]

    def let_go_height(turn_start: int) -> float:
        """How high the device was when Genau handed it to the script turn
        opening at *turn_start* — the top of the ramp down."""
        if let_go_at is not None and let_go_at[0] >= turn_start:
            return let_go_at[1]
        if stroke is None:
            return 0.0
        return stroke_at((turn_start - position_ms) / step)

    def at(sample_ms: int, planned: float, column: int) -> tuple[float, str]:
        """One sample of the line: how high, and whose stretch it is in.

        *column* is how many samples past the playhead this one sits, and is
        what the stroke Genau is sending *right now* is read at — the column
        index rather than ``(sample_ms - position_ms) / step``, because those
        differ by the sub-knot slide.  The painter leaves the live run unshifted
        (Genau's own republishing is what moves it), so reading it at the shifted
        time rounded the index up and down as the playhead crossed each
        half-knot, and the whole blue stroke twitched a sample sideways and back.
        """
        turn_start, _turn_end = script.turn_bounds_at(sample_ms)
        if script.is_resting_at(sample_ms):
            if stroke is None:
                # Nobody is going to take these stretches: in Nau's own mode
                # there is no Genau behind the screen, and the script's driver
                # rests the device through them.
                return 0.0, DRIVEN_BY_NOTHING
            if turn_start is None:
                # Genau has had the device since before the video began, so its
                # stroke is simply running: sample 0 of what it published is now.
                return stroke_at(column), DRIVEN_BY_GENAU
            since = sample_ms - turn_start
            if since < HANDOFF_RAMP_MS:
                # The climb out of the park onto the stroke's floor.  Genau holds
                # its swing through this, so the climb costs the stroke nothing.
                return floor_height * max(0, since) / HANDOFF_RAMP_MS, DRIVEN_BY_NEUTRAL
            if turn_start <= position_ms:
                return stroke_at(column), DRIVEN_BY_GENAU
            # A turn that has not opened yet: its stroke starts at the top of the
            # climb, so the wave is anchored there rather than to now.
            return stroke_at(
                (sample_ms - turn_start - HANDOFF_RAMP_MS) / step), DRIVEN_BY_GENAU
        if turn_start is not None:
            since = sample_ms - turn_start
            if since < HANDOFF_RAMP_MS:
                # The ramp down from wherever Genau left the device onto the
                # park, which is where the script's own plan begins.
                return (let_go_height(turn_start)
                        * (1 - max(0, since) / HANDOFF_RAMP_MS)), DRIVEN_BY_NEUTRAL
        who = (DRIVEN_BY_NEUTRAL if script.is_parked_at(sample_ms)
               else DRIVEN_BY_FUNSCRIPT)
        return planned, who

    values: list[float] = []
    whos: list[str] = []
    for index in range(TRACE_SAMPLES):
        value, who = at(round(anchor_ms + index * step), scripted[index], index)
        values.append(value)
        whos.append(who)

    marks: list[tuple[int, str]] = []
    for index, who in enumerate(whos):
        if not marks or marks[-1][1] != who:
            marks.append((index, who))
    # The knot just past the right border, so the line shifted left by ``slide``
    # still reaches the box's edge — the same choice the loop would have made
    # for an eighty-first sample.
    edge, _who = at(
        round(anchor_ms + TRACE_SAMPLES * step), scripted[TRACE_SAMPLES], TRACE_SAMPLES)
    # The dot rides the line it is drawn on: while a script has the device that
    # is the plan (with whatever ramp is still playing out), and while Genau has
    # it, the position Genau published — the device's own, at its own rate,
    # rather than the line's nearest knot.
    marker = base.position
    if osr2_has_script:
        height, _who = at(position_ms, script.planned_position_at(position_ms) / 100, 0)
        marker = round(height * POSITION_MAX)
    return replace(
        base,
        waveform=tuple(values),
        slide=slide,
        edge=edge,
        # Always said, even for a single run: the painter's fallback colour for
        # an empty ``segments`` is the OSR2 state, and that state trails the
        # arbiter by a beat at every handoff — the whole stroke flashed the
        # script's green for a frame each time the device changed hands.  The
        # marks are stable while the picture is, so the readout still compares
        # equal to itself between repaints.
        segments=tuple(marks),
        position=marker,
    )
