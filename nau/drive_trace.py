"""What the device is about to be asked to do, and by whom — the trace's model.

The line is four things in a row, and nothing else:

    whatever Genau is doing
    a ramp from where that leaves the device down onto the park
    whatever the funscript is doing
    a ramp back up to where Genau's stroke begins

Green is the script scripting, blue is Genau stroking, grey is a ramp or the
rest between them — nobody drives through those, the device is being handed
over.

Every boundary is a time the script fixes: a turn opens QUIET_LEAD_IN_MS before
its cluster, closes QUIET_LEAD_OUT_MS after it, and the funscript does not
change while it plays.  The devices walk the same ramps — Nau's driver parks
over the handoff ramp when it takes the device, Genau climbs back out of the
park over the same one — so the picture and the wire share one schedule.

Two disciplines keep the picture still while it slides:

* The stroke is only ever asked WHAT HEIGHT, never WHEN.  Asking the live
  stroke when anything happens (its next floor-touch, its own let-go) gave
  answers that moved under the picture every publish — the flicker, the
  vanishing final cycle.
* Every read is anchored to something that does not move.  The one number that
  cannot be recomputed — the height Genau was at when it let go — arrives
  latched in Genau's own publish (``DriveHud.let_go``), captured at the source
  before the resting phase destroys it.

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
)

# The window into the script slides continuously, so read at the raw playhead it
# would move — and repaint the console — at Nau's full frame rate.  Quantized to
# the cadence Genau's own publishes already repaint at while the stroke scrolls,
# the green moves exactly as smoothly as the blue, for the same cost.
_SLIDE_QUANTUM_MS = 40

# A resumed stroke opening this close to the park needs no climb: the sender
# skips its rise there (the park already IS the stroke's floor, full amplitude)
# and the blue begins the moment Genau's turn does.  The same two percent the
# sender uses, so the picture and the device skip together.
_PARK_EPSILON = 0.02


def drive_readout(
    published: DriveHud | None,
    *,
    script,
    position_ms: int,
    speed: float = 1.0,
    genau_behind: bool,
) -> DriveHud:
    """The readout to draw, folding the funscript's own shape into it.

    *published* is Genau's readout as it last said it, or None where there is no
    Genau behind the screen (Nau's own mode); *genau_behind* says whether Genau
    is there to take the gaps.  Who holds the device right now is read off the
    publish itself — ``let_go`` is set exactly while Genau has handed it over —
    rather than off the console's round-tripped state, which trails the arbiter
    by a couple of publish intervals and lied to the picture at every seam.

    The span is Genau's own — it publishes the number with its trace — scaled by
    the playback rate, because the trace covers wall-clock time and at double
    speed twice as much of the script goes past in it.  The two handoff ramps
    scale the same way: the device walks them in wall time.
    """
    base = published or DriveHud()
    if script is None:
        return base
    position_ms -= position_ms % _SLIDE_QUANTUM_MS
    span_ms = round(base.trace_seconds * 1000 * speed)
    step = span_ms / max(1, TRACE_SAMPLES - 1)
    ramp_ms = round(HANDOFF_RAMP_MS * speed)
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

    def stroke_at(index: float) -> float:
        """The published stroke at a possibly fractional sample offset.

        Interpolated, not rounded: a rounded index snapped between neighbours
        as the playhead crossed each half-knot, and every read that fed a ramp
        top or a future wave shimmered by a whole sample's height.
        """
        if index <= 0:
            return stroke[0]
        if index >= TRACE_SAMPLES - 1:
            return stroke[TRACE_SAMPLES - 1]
        whole = int(index)
        frac = index - whole
        if not frac:
            return stroke[whole]
        return stroke[whole] * (1 - frac) + stroke[whole + 1] * frac

    # Where a future resumed stroke opens inside the published buffer.  A
    # takeover always rests the phase first, so every future Genau turn begins
    # at the stroke's floor: parked, the publish already starts there (offset
    # 0); live, the floor is wherever the buffer's lowest sample sits.  Without
    # this the future blue was read at fixed offsets into a buffer that scrolls,
    # and it treadmilled in place while everything around it stood still.
    resume_base = 0.0
    if stroke is not None and base.let_go is None:
        resume_base = float(min(range(TRACE_SAMPLES), key=stroke.__getitem__))
    # How long the climb out of the park takes, in media time.  Zero when the
    # resumed stroke already opens at the park — then the blue begins the moment
    # Genau's turn does, exactly as the sender's skipped rise plays it.
    climb_ms = 0
    if stroke is not None and stroke_at(resume_base) > _PARK_EPSILON:
        climb_ms = ramp_ms

    def genau_height(sample_ms: int) -> float:
        """The blue line's height at *sample_ms* — the one place stroke reads
        happen, so every seam that needs the blue's value reads the same one.

        Two anchors, one per state of the publish.  A stroke Genau is RUNNING
        republishes from its advancing phase, so reading it at the time offset
        (sample - now) returns the stroke's value at that fixed absolute time,
        frame after frame — the whole line then shifts on the painter's one
        slide like everything else.  A stroke still WAITING (a turn ahead, or a
        climb still running) is frozen at phase 0, and its own start — the top
        of the climb — is the anchor instead.
        """
        if stroke is None:
            return 0.0
        probe = sample_ms if script.is_resting_at(sample_ms) else max(sample_ms - 1, 0)
        began, _ = script.turn_bounds_at(probe)
        if began is None or began + climb_ms <= position_ms:
            return stroke_at((sample_ms - position_ms) / step)
        return stroke_at(resume_base + (sample_ms - began - climb_ms) / step)

    def let_go_height(turn_start: int) -> float:
        """The top of the descent ramp for the script turn opening at
        *turn_start*: where the blue leaves the device.

        Once the handoff has happened Genau's publish says it outright — the
        latched ``let_go`` — and before that it is the drawn blue's own value at
        the boundary, so the ramp meets the line it descends from either way.
        """
        if base.let_go is not None and position_ms >= turn_start:
            return base.let_go
        return genau_height(turn_start)

    def at(sample_ms: int, planned: float) -> tuple[float, str]:
        """One sample of the line: how high, and whose stretch it is in."""
        if script.is_resting_at(sample_ms):
            # Genau's stretch.  It opens with the climb out of the park.
            if stroke is None:
                # Nobody is going to take these stretches: in Nau's own mode
                # there is no Genau behind the screen, and the script's driver
                # rests the device through them.
                return 0.0, DRIVEN_BY_NOTHING
            began, _ = script.turn_bounds_at(sample_ms)
            if began is not None and climb_ms:
                since = sample_ms - began
                if since < climb_ms:
                    # The climb: park up to wherever the resumed stroke opens.
                    # Genau holds its swing through it, so it costs no stroke.
                    top = stroke_at(resume_base)
                    return top * max(0, since) / climb_ms, DRIVEN_BY_NEUTRAL
            return genau_height(sample_ms), DRIVEN_BY_GENAU
        # The script's stretch — opening with the ramp down from wherever the
        # blue left the device onto the park, where the script's plan begins.
        turn_start, _turn_end = script.turn_bounds_at(sample_ms)
        if turn_start is not None:
            since = sample_ms - turn_start
            if since < ramp_ms:
                return (let_go_height(turn_start)
                        * (1 - max(0, since) / ramp_ms)), DRIVEN_BY_NEUTRAL
        who = (DRIVEN_BY_NEUTRAL if script.is_parked_at(sample_ms)
               else DRIVEN_BY_FUNSCRIPT)
        return planned, who

    values: list[float] = []
    whos: list[str] = []
    for index in range(TRACE_SAMPLES):
        value, who = at(round(anchor_ms + index * step), scripted[index])
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
        round(anchor_ms + TRACE_SAMPLES * step), scripted[TRACE_SAMPLES])
    # The dot rides the drawn line, always.  Genau's published position is used
    # only while the playhead is inside live blue — where it IS the line, at the
    # device's own finer rate.  Everywhere else (both ramps, the plan, the
    # rests) the height comes from the same function that drew the line, so the
    # dot can never ride a line that is not there: keying this on the console's
    # osr2 instead put the dot on Genau's frozen position over a grey ramp at
    # every handoff, for as long as the console lagged the arbiter.
    height, who_now = at(position_ms, script.planned_position_at(position_ms) / 100)
    if who_now == DRIVEN_BY_GENAU:
        marker = base.position
    else:
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
