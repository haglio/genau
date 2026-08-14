"""What the device is about to be asked to do, and by whom — the trace's model.

The drive readout draws one line across a stretch of time running forward from
the playhead.  Who is driving over that stretch is not one answer: a funscript
drives while it is scripting, Genau drives the true rests, and between them the
device changes hands.  This walks the span deciding per sample, so the line is
green where the script strokes, blue where Genau's stroke runs, and light grey
through the buffer between them.

The buffer is a shape of its own, not a gap: the device glides down from the
stroke's floor onto its park, waits there, and climbs back up to the floor
before the next swing.  Both of those ramps belong to the buffer rather than to
either driver — nobody is stroking through them, the device is being handed
over — so they are drawn in the buffer's grey, and Genau's blue is only ever
Genau's actual stroke.

One rule builds the whole line: for each sample, whose turn it is, and where in
that turn it falls.  It replaces a picture that was assembled from a prediction
plus a forward-extension pass plus a patch for the moment the console caught up
— three constructions that had to agree exactly and did not, so the seam jumped
whenever they disagreed.

The one thing that cannot be read off the script is when Genau's turn *ends*:
the arbiter holds the handoff until the stroke touches its floor, so it ends on
a moment only the live stroke knows.  That is why the touch is interpolated
rather than read off the nearest sample — see
:func:`player_core.drive_readout.floor_touch_ms` — and why, once the handoff
has happened, the recorded flip stands in for the prediction.

Kept out of :mod:`nau.app` and free of Pillow, like :mod:`nau.console` is, so the
shape of the picture is testable without a window or a font.
"""
from __future__ import annotations

from dataclasses import replace

from player_core.funscript import PARK_SETTLE_MS

from player_core.drive_readout import (
    DRIVEN_BY_FUNSCRIPT,
    DRIVEN_BY_GENAU,
    DRIVEN_BY_NEUTRAL,
    DRIVEN_BY_NOTHING,
    FLOOR_WAIT_CAP_MS,
    POSITION_MAX,
    TAKEOVER_RISE_MS,
    TRACE_SAMPLES,
    DriveHud,
    floor_touch_ms,
    stroke_floor,
)

# The window into the script slides continuously now, so read at the raw
# playhead it would move — and repaint the console — at Nau's full frame rate.
# Quantized to the cadence Genau's own publishes already repaint at while the
# stroke scrolls, the green moves exactly as smoothly as the blue, for the
# same cost.
_SLIDE_QUANTUM_MS = 40

# A floor this close to the park needs no ramp at all — his rule: at full
# amplitude the grey begins right at the touch-down and the stroke resumes
# straight out of the park, because the two heights are the same height.
_PARK_EPSILON = 0.02


def drive_readout(
    published: DriveHud | None,
    *,
    script,
    position_ms: int,
    speed: float = 1.0,
    genau_behind: bool,
    osr2_has_script: bool,
    script_took_over_ms: int | None = None,
) -> DriveHud:
    """The readout to draw, folding the funscript's own shape into it.

    *published* is Genau's readout as it last said it, or None where there is no
    Genau behind the screen (Nau's own mode).  *genau_behind* says whether Genau
    is there to take the gaps; *osr2_has_script* is whether a script has the
    device *now*; *script_took_over_ms* is the playhead position at which it
    took it, which the caller reads off the console's own handoff edge.

    The span is Genau's own — it publishes the number with its trace — scaled by
    the playback rate, because the trace covers wall-clock time and at double
    speed twice as much of the script goes past in it.  Sampling the script on
    its own fixed grid (:meth:`player_core.funscript.Funscript.planned_trace`)
    is what keeps the shape still: resampled from the playhead every frame,
    every peak landed somewhere slightly different and the line boiled in place.
    """
    base = published or DriveHud()
    if script is None:
        return base
    position_ms -= position_ms % _SLIDE_QUANTUM_MS
    span_ms = round(base.trace_seconds * 1000 * speed)
    step = span_ms / max(1, TRACE_SAMPLES - 1)
    # The device's *plan*, not the script's interpolated line: through the
    # buffers around each handoff the driver rests the device at its park and
    # rises only to meet the next cluster, and a green line that held the last
    # position across those stretches was a picture the device visibly
    # contradicted.  The window sits on whole knots — the script never changes
    # while it plays, so its picture is computed once and only reread — and the
    # leftover fraction of a knot rides along as ``slide`` for the painter to
    # shift the stable shape by.
    scripted, slide = script.planned_trace_window(position_ms, span_ms, TRACE_SAMPLES)
    if len(scripted) != TRACE_SAMPLES + 1:
        return base
    # Sample times anchored to the window's own knots, so what each sample says
    # never depends on where inside a knot the playhead sits.
    anchor_ms = position_ms - slide * step
    stroke = base.waveform if len(base.waveform) == TRACE_SAMPLES else None
    if not genau_behind:
        stroke = None
    # Where the stroke bottoms out — its floor, the lowest point the current
    # centre and amplitude reach.  Both ramps run between here and the park, it
    # is where the frozen stroke waits through a funscript's turn, and it is the
    # same rule the arbiter ends Genau's turn on, so the picture, the resume and
    # the device agree.
    floor_height = stroke_floor(base.center, base.amplitude) if stroke else 0.0
    ramped = floor_height > _PARK_EPSILON
    rise_ms = TAKEOVER_RISE_MS if ramped else 0

    def stroke_at(index: int) -> float:
        return stroke[min(max(index, 0), TRACE_SAMPLES - 1)]

    hands_over: dict[int | None, float] = {}

    def hands_over_at(turn_start: int | None) -> float:
        """When Genau really lets go, for the script turn opening at *turn_start*.

        Its own rest ends there, but the arbiter holds the device until the
        stroke comes down onto its floor, so that is where the blue ends.  Once
        the handoff has actually happened the recorded flip says it outright —
        the frozen stroke can no longer be asked when it would have come down.
        """
        if turn_start is None:
            return float("-inf")
        if turn_start not in hands_over:
            hands_over[turn_start] = _genau_lets_go(
                turn_start,
                now_ms=position_ms,
                stroke=stroke,
                floor=floor_height,
                pitch_ms=step,
                recorded=script_took_over_ms,
                genau_has_device=not osr2_has_script,
            )
        return hands_over[turn_start]

    def at(sample_ms: int, planned: float) -> tuple[float, str]:
        """One sample of the line: how high, and whose stretch it is in."""
        turn_start, _turn_end = script.turn_bounds_at(sample_ms)
        if script.is_resting_at(sample_ms):
            # Genau's turn.  It opens with the climb out of the park, unless
            # the stroke's floor already rests there.
            if stroke is None:
                # Nobody is going to take these stretches: in Nau's own mode
                # there is no Genau behind the screen, and the script's driver
                # rests the device through them.
                return 0.0, DRIVEN_BY_NOTHING
            if turn_start is None:
                # Genau has had the device since before the video began, so its
                # stroke is simply running: sample 0 of what it published is now.
                return stroke_at(round((sample_ms - position_ms) / step)), DRIVEN_BY_GENAU
            since = sample_ms - turn_start
            if ramped and since < rise_ms:
                return floor_height * max(0.0, since) / rise_ms, DRIVEN_BY_NEUTRAL
            if turn_start <= position_ms:
                # The turn Genau is in the middle of: its published stroke is
                # sampled forward from now, so the picture rides the phase it
                # is actually on rather than one reconstructed from the start.
                return stroke_at(round((sample_ms - position_ms) / step)), DRIVEN_BY_GENAU
            return stroke_at(round((sample_ms - turn_start - rise_ms) / step)), DRIVEN_BY_GENAU
        # The script's turn — but only from the moment Genau lets go.
        let_go = hands_over_at(turn_start)
        if sample_ms < let_go:
            return stroke_at(round((sample_ms - position_ms) / step)), DRIVEN_BY_GENAU
        if ramped and sample_ms < let_go + PARK_SETTLE_MS:
            fallen = (sample_ms - let_go) / PARK_SETTLE_MS
            return floor_height * (1 - fallen), DRIVEN_BY_NEUTRAL
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
    edge, _who = at(round(anchor_ms + TRACE_SAMPLES * step), scripted[TRACE_SAMPLES])
    # The dot rides the line it is drawn on: while a script has the device that
    # is the plan (with whatever ramp is still playing out), and while Genau has
    # it, the position Genau published — the device's own, at its own rate,
    # rather than the line's nearest knot.
    marker = base.position
    if osr2_has_script:
        height, _who = at(position_ms, script.planned_position_at(position_ms) / 100)
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


def _genau_lets_go(
    turn_start: int,
    *,
    now_ms: int,
    stroke,
    floor: float,
    pitch_ms: float,
    recorded: int | None,
    genau_has_device: bool,
) -> float:
    """When Genau's turn really ends, for a script turn opening at *turn_start*.

    Its rest ends at *turn_start*, but the arbiter holds the device until the
    stroke comes down onto its floor — so while Genau still has it, this asks
    the published stroke the same question, with the same cap.  Interpolated
    rather than snapped to the nearest sample: the stroke is re-rendered from a
    moving phase every publish, and an answer that jumped a whole sample frame
    to frame took the end of the blue with it.

    Once the script has the device the question is settled and the frozen
    stroke can no longer answer it, so the flip the caller recorded stands —
    or, with none recorded yet, the rest's own end.
    """
    if not genau_has_device:
        if recorded is not None and turn_start <= recorded <= now_ms:
            return recorded
        return turn_start
    if stroke is None:
        return turn_start
    ahead = max(0.0, turn_start - now_ms)
    touch = floor_touch_ms(stroke, floor, pitch_ms=pitch_ms, start_ms=ahead)
    if touch is None:
        return now_ms + ahead + FLOOR_WAIT_CAP_MS
    return now_ms + min(touch, ahead + FLOOR_WAIT_CAP_MS)
