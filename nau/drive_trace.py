"""What the device is about to be asked to do, and by whom — the trace's model.

The drive readout draws one line across a stretch of time running forward from
the playhead.  Who is driving over that stretch is not one answer: a funscript
drives while it is scripting, Genau drives the true rests, and around each
handoff sits a neutral buffer where the device rests at its park — the script
technically holds it, but is sending nothing but the rest.  This walks the span
deciding per sample, so the line is green where the script strokes, light grey
through the neutral buffers, and blue where Genau's stroke runs, joined at the
moments the device changes hands.

That boundary is not a guess.  Fun Time hands the OSR2 over on exactly the rule
used here — the script has it wherever it is not resting — so what the trace
shows ahead of the seam is the seam that is coming.

Kept out of :mod:`nau.app` and free of Pillow, like :mod:`nau.console` is, so the
shape of the picture is testable without a window or a font.
"""
from __future__ import annotations

from dataclasses import replace

from player_core.funscript import PARK_SETTLE_MS, QUIET_LEAD_IN_MS

from player_core.drive_readout import (
    DRIVEN_BY_FUNSCRIPT,
    DRIVEN_BY_GENAU,
    DRIVEN_BY_NEUTRAL,
    DRIVEN_BY_NOTHING,
    FLOOR_TOUCH_TOLERANCE,
    POSITION_MAX,
    TRACE_SAMPLES,
    DriveHud,
    stroke_floor,
)

# The window into the script slides continuously now, so read at the raw
# playhead it would move — and repaint the console — at Nau's full frame rate.
# Quantized to the cadence Genau's own publishes already repaint at while the
# stroke scrolls, the green moves exactly as smoothly as the blue, for the
# same cost.
_SLIDE_QUANTUM_MS = 40

# A floor this close to the park needs no settle glide at all — his rule: at
# full amplitude the grey begins right at the touch-down.  Distinct from
# FLOOR_TOUCH_TOLERANCE, which is about *finding* a touch in sampled data.
_PARK_EPSILON = 0.02


def drive_readout(
    published: DriveHud | None,
    *,
    script,
    position_ms: int,
    speed: float = 1.0,
    genau_behind: bool,
    osr2_has_script: bool,
) -> DriveHud:
    """The readout to draw, folding the funscript's own shape into it.

    *published* is Genau's readout as it last said it, or None where there is no
    Genau behind the screen (Nau's own mode).  *genau_behind* says whether Genau
    is there to take the gaps; *osr2_has_script* is whether a script has the
    device *now*, which is what decides where the position marker comes from.

    The span is Genau's own — it publishes the number with its trace — scaled by
    the playback rate, because the trace covers wall-clock time and at double
    speed twice as much of the script goes past in it.  Sampling the script on
    its own fixed grid (:meth:`player_core.funscript.Funscript.trace`) is what
    keeps the shape still: resampled from the playhead every frame, every peak
    landed somewhere slightly different and the line boiled in place.
    """
    base = published or DriveHud()
    if script is None:
        return base
    position_ms -= position_ms % _SLIDE_QUANTUM_MS
    span_ms = round(base.trace_seconds * 1000 * speed)
    step = span_ms / max(1, TRACE_SAMPLES - 1)
    # The device's *plan*, not the script's interpolated line: through the
    # handed-over buffers around each handoff the driver rests the device at
    # its park and rises only to meet the next cluster, and a green line that
    # held the last position across those stretches was a picture the device
    # visibly contradicted.  The window sits on whole knots — the script never
    # changes while it plays, so its picture is computed once and only reread —
    # and the leftover fraction of a knot rides along as ``slide`` for the
    # painter to shift the stable shape by.
    scripted, slide = script.planned_trace_window(position_ms, span_ms, TRACE_SAMPLES)
    if len(scripted) != TRACE_SAMPLES + 1:
        return base
    # Sample times anchored to the window's own knots, so what each sample says
    # never depends on where inside a knot the playhead sits.
    anchor_ms = position_ms - slide * step
    # Whoever has the device where the script does not.  In Hybrid that is Genau's
    # own stroke, drawn forward from the phase it is parked on — the very stroke it
    # will resume with.  In Nau nobody does: the script's driver rests the device,
    # so the picture is the floor rather than a stroke that is not coming.
    idle_driver = DRIVEN_BY_GENAU if genau_behind else DRIVEN_BY_NOTHING
    stroke = base.waveform if len(base.waveform) == TRACE_SAMPLES else None

    # The published stroke is a run of *stroke time* — sample 0 is the phase it
    # is on (or parked on), each later sample one step of stroking after that —
    # so it is spent per stroking sample rather than read by screen position.
    # Anchored that way, the picture the stretch after a seam shows is pinned to
    # the seam and slides left with it; read by screen position it sat still
    # while the seam swept over it, revealed rather than approaching.  Scripted
    # stretches spend none of it, which is the phase holding still while the
    # script drives.
    # Where the stroke bottoms out — its floor, the lowest point the current
    # center and amplitude reach.  The settle onto the park opens here: it is
    # stable (it moves only when a control does), it is where the frozen stroke
    # rests through a funscript's turn, and it is the same rule the arbiter
    # uses to end Genau's turn, so the settle, the resume picture and the
    # device agree.
    floor_height = stroke_floor(base.center, base.amplitude)

    values: list[float] = []
    whos: list[str] = []
    resting_flags: list[bool] = []
    stroked = 0
    for index in range(TRACE_SAMPLES):
        at_ms = round(anchor_ms + index * step)
        resting = script.is_resting_at(at_ms)
        if resting:
            who = idle_driver
            taking_over = bool(whos) and whos[-1] != idle_driver
            if taking_over:
                # The device is wherever the plan leaves it — its park, once
                # the script has wound down — and the takeover glide walks it
                # onto the stroke from there, so the line after the seam starts
                # at that height rather than jumping to the stroke's.
                values.append(scripted[index])
            elif stroke is not None:
                values.append(stroke[min(stroked, TRACE_SAMPLES - 1)])
            else:
                values.append(0.0)
            stroked += 1
        else:
            who = (DRIVEN_BY_NEUTRAL if script.is_parked_at(at_ms)
                   else DRIVEN_BY_FUNSCRIPT)
            values.append(scripted[index])
        whos.append(who)
        resting_flags.append(resting)

    # Genau's turn ends on its floor, and really does: the arbiter holds the
    # handoff until the stroke touches its floor, so the blue runs PAST the
    # rest's end to that touch — cutting it at the boundary drew a promise the
    # device then broke, swinging on while the picture showed flat grey.  From
    # the touch: a stroke whose floor sits above the park glides down over the
    # driver's settle, still in blue; one already touching the park needs no
    # glide at all, and the grey flatline begins right there — his rule.
    if genau_behind and stroke is not None:
        boundaries = [b for b in range(1, TRACE_SAMPLES)
                      if resting_flags[b - 1]
                      and whos[b - 1] == DRIVEN_BY_GENAU
                      and not resting_flags[b]]
        # The window can also OPEN inside the stretch Genau is still finishing:
        # once the playhead crosses the rest's end, the boundary scrolls off the
        # left edge while the arbiter still holds the handoff for the touch —
        # and without this the whole leading stretch went grey the moment the
        # rest ended, wiping up to a full cycle of blue the device was still
        # going to stroke.  The OSR2 state is the witness: until it says the
        # script has the device, the leading buffer is still Genau's.
        if (not resting_flags[0] and whos[0] == DRIVEN_BY_NEUTRAL
                and not osr2_has_script):
            boundaries.insert(0, 0)
        for boundary in boundaries:
            index = boundary
            touched = False
            while index < TRACE_SAMPLES and whos[index] == DRIVEN_BY_NEUTRAL:
                value = stroke[min(stroked, TRACE_SAMPLES - 1)]
                stroked += 1
                values[index] = value
                whos[index] = DRIVEN_BY_GENAU
                index += 1
                if value <= floor_height + FLOOR_TOUCH_TOLERANCE:
                    touched = True
                    break
            if not touched:
                continue
            touch = index - 1
            while index < TRACE_SAMPLES and whos[index] == DRIVEN_BY_NEUTRAL:
                elapsed = (index - touch) * step
                if floor_height <= _PARK_EPSILON or elapsed >= PARK_SETTLE_MS:
                    break
                # The settle down from the floor onto the park, anchored at the
                # touch where the pause really lands.
                values[index] = floor_height * (1 - elapsed / PARK_SETTLE_MS)
                whos[index] = DRIVEN_BY_GENAU
                index += 1

    marks: list[tuple[int, str]] = []
    for index, who in enumerate(whos):
        if not marks or marks[-1][1] != who:
            marks.append((index, who))
    # The knot just past the right border, so the line shifted left by ``slide``
    # still reaches the box's edge — the same choice the loop would have made
    # for an eighty-first sample.
    if script.is_resting_at(round(anchor_ms + TRACE_SAMPLES * step)):
        edge = (stroke[min(stroked, TRACE_SAMPLES - 1)]
                if stroke is not None else 0.0)
    else:
        edge = scripted[TRACE_SAMPLES]
    # The dot down the edge glides with the device: right after the handoff the
    # driver is still settling the device onto the park, and a dot that
    # teleported to the floor while the OSR2 was visibly easing down called the
    # picture a liar.
    marker = base.position
    if osr2_has_script:
        planned = script.planned_position_at(position_ms)
        onset = script.next_active_ms(position_ms)
        if genau_behind and onset is not None and script.is_parked_at(position_ms):
            since_handoff = position_ms - (onset - QUIET_LEAD_IN_MS)
            if 0 <= since_handoff < PARK_SETTLE_MS:
                fraction = since_handoff / PARK_SETTLE_MS
                planned = floor_height * 100 * (1 - fraction) + planned * fraction
        marker = round(planned / 100 * POSITION_MAX)
    return replace(
        base,
        waveform=tuple(values),
        slide=slide,
        edge=edge,
        # Always said, even for a single run: the painter's fallback color for
        # an empty ``segments`` is the OSR2 state, and that state trails the
        # arbiter by a beat at every handoff — the whole stroke flashed the
        # script's green for a frame each time the device changed hands.  The
        # marks are stable while the picture is, so the readout still compares
        # equal to itself between repaints.
        segments=tuple(marks),
        # The dot down the edge is where the device is: the plan (with its
        # settle glide) while a script has it, the stroke position Genau
        # published while Genau does.
        position=marker,
    )
