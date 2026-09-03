"""What the device is about to be asked to do, and by whom — the trace's model.

The line is four things in a row, and nothing else:

    whatever Genau is doing
    a ramp from where that leaves the device down onto the park
    whatever the funscript is doing
    a ramp back up to where Genau's stroke begins

Green is the script scripting, blue is Genau stroking, gray is a ramp or the
rest between them — nobody drives through those, the device is being handed
over.

Every boundary is a time the script fixes: a turn opens QUIET_LEAD_IN_MS before
its cluster, closes QUIET_LEAD_OUT_MS after it, and the funscript does not
change while it plays.  The devices walk the same ramps — Nau's driver parks
over the handoff ramp when it takes the device, Genau climbs back out of the
park over the same one — so the picture and the wire share one schedule.

Two disciplines keep the picture still while it slides:

* The stroke is only ever asked WHAT HEIGHT, never WHEN.  A live stroke asked
  *when* something happens — its next floor-touch, its own let-go — answers
  differently every publish, and the picture would move with it.
* Every read is anchored to something that does not move.  The one number that
  cannot be recomputed — the height Genau was at when it let go — arrives
  latched in Genau's own publish (``DriveHud.let_go``), captured at the source
  before the resting phase destroys it.

Kept out of :mod:`nau.app` and free of Pillow, so the shape of the picture is
testable without a window or a font.
"""
from __future__ import annotations

from dataclasses import replace

from player_core.funscript import HANDOFF_RAMP_MS, PARK_TOUCH_WAIT_CAP_MS

from player_core.drive_readout import (
    DRIVEN_BY_FUNSCRIPT,
    DRIVEN_BY_GENAU,
    DRIVEN_BY_NEUTRAL,
    DRIVEN_BY_NOTHING,
    POSITION_MAX,
    TRACE_SAMPLES,
    DriveHud,
)

from .descent_latch import DescentChoice, DescentLatch, DriveKey

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

# How far past a turn boundary the touch-down scan starts.  The arbiter only
# learns the boundary through the status file and its own tick, so it cannot
# stop the device at a touch inside that lag — a touch the picture chose there
# would be one the device sails past.  Both sides skip the lag window and take
# the first touch after it, so they take the same one.
_TOUCH_LAG_MS = 350

# The blue's final approach to its seam eases onto the seam's own value over
# this long.  The live blue breathes a hair with every publish (the read's age
# varies by a beat), which is invisible mid-wave — the whole line breathes
# together — but at the seam the latched gray amplifies it into a tiny
# indecision about where the join sits.  Feathered onto the latched value, the
# seam's neighborhood converges to a constant and cannot flicker, at the cost
# of a few percent of bend across the last two or three columns.
_SEAM_FEATHER_MS = 300

# How close the boundary must be before a descent's choice is latched.  The
# published wave is a projection from the CURRENT phase and pace, and over ten
# seconds the real engine drifts off it (sync nudges the pace continuously) —
# a touch latched the moment its turn scrolled into view arrived a whole
# swing wrong by the time the playhead reached it.  Inside this horizon the
# projection is as fresh as the one the arbiter will use, so the two agree;
# outside it the choice stays live, a forecast refining as it approaches.
_TOUCH_FREEZE_AHEAD_MS = 3000


def drive_readout(
    published: DriveHud | None,
    *,
    script,
    position_ms: int,
    speed: float = 1.0,
    genau_behind: bool,
    latch: DescentLatch | None = None,
) -> DriveHud:
    """The readout to draw, folding the funscript's own shape into it.

    *published* is Genau's readout as it last said it, or None where there is no
    Genau behind the screen (Nau's own mode); *genau_behind* says whether Genau
    is there to take the gaps.  Who holds the device right now is read off the
    publish itself — ``let_go`` is set exactly while Genau has handed it over —
    rather than off the console's round-tripped state, which trails the arbiter
    by a couple of publish intervals.

    *latch* is the caller's :class:`nau.descent_latch.DescentLatch`, one choice
    per approaching turn: a descent's top is SELECTED once and then held,
    re-selected only when something real moves it (the controls, a handoff, the
    wave realigning after an OmniPause).  Re-read live every frame it would
    breathe with the beat between Genau's publish cadence and the frame clock.

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

        Interpolated, not rounded: the index falls between samples, and a
        rounded one moves by a whole sample's height every time the playhead
        crosses a half-knot.
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
    # 0); live, the floor is wherever the buffer's lowest sample sits.  A fixed
    # offset into a buffer that scrolls would treadmill in place.
    resume_base = 0.0
    if stroke is not None and base.let_go is None:
        resume_base = float(min(range(TRACE_SAMPLES), key=stroke.__getitem__))
    # How long the climb out of the park takes, in media time.  Zero when the
    # resumed stroke already opens at the park — then the blue begins the moment
    # Genau's turn does, exactly as the sender's skipped rise plays it.
    climb_ms = 0
    if stroke is not None and stroke_at(resume_base) > _PARK_EPSILON:
        climb_ms = ramp_ms

    def genau_height(sample_ms: int, began: int | None) -> float:
        """The blue line's height at *sample_ms*, for the Genau stretch that
        opened at *began* (None: held since before the video).

        The stretch is the CALLER's to name, because the blue is read in two
        places with different neighbors: its own resting samples, and the
        extension past a park-floored boundary, whose samples sit inside the
        SCRIPT's turn — resolved from the sample itself, those picked up the
        script turn's bounds and re-anchored the live wave as if it were a
        future resumed one, and the drawn ending landed a whole swing wrong.

        Two anchors, one per state of the publish: a RUNNING stroke is read at
        the time offset (sample - now), which returns the value at that fixed
        absolute time frame after frame; a WAITING one (a turn ahead, a climb
        still running) is frozen at phase 0 and anchored at its own start.
        """
        if stroke is None:
            return 0.0
        if began is None or began + climb_ms <= position_ms:
            return stroke_at((sample_ms - position_ms) / step)
        return stroke_at(resume_base + (sample_ms - began - climb_ms) / step)

    def park_touch_after(turn_start: int, began: int | None) -> int | None:
        """The blue's first touch-down on the park at-or-after *turn_start*
        (plus the arbiter's lag window), for the stretch that opened at *began*.

        Only a stroke whose floor rests ON the park has one — that is the case
        with no ramp: the blue swings on to this touch and the gray runs flat
        from there, exactly where the arbiter sets the device down.  None means
        the ramp case (a raised floor, or a stroke too slow to come down inside
        the shared cap).  A touch beyond the published horizon reads as a cut
        at the boundary itself for now; the freeze horizon guarantees it is
        recomputed before it is ever latched.
        """
        if stroke is None or min(stroke) > _PARK_EPSILON:
            return None
        scan_from = turn_start + round(_TOUCH_LAG_MS * speed)
        scan_to = scan_from + round(PARK_TOUCH_WAIT_CAP_MS * speed)
        if scan_to > position_ms + span_ms:
            return turn_start
        at_ms = float(scan_from)
        while at_ms <= scan_to:
            if genau_height(round(at_ms), began) <= _PARK_EPSILON:
                return round(at_ms)
            at_ms += step / 4
        return None

    def descent_entry(turn_start: int) -> tuple[float, int | None]:
        """How the blue leaves the device at *turn_start*: ``(ramp top,
        touch-down)``.

        With a touch-down, there is no ramp — the blue runs to the touch and
        the gray is flat.  Without one, the gray ramps down from the top: the
        published ``let_go`` once the handoff has happened, the drawn blue's
        own boundary value before it.  The choice stays LIVE while the
        boundary is far — a forecast off a projection that drifts — and is
        latched once inside the freeze horizon, where the projection is as
        fresh as the arbiter's own; from there it cannot move again.
        """
        latched = latch.choice_for(turn_start) if latch is not None else None
        key = DriveKey.cut_from(base)
        if latched is not None and latched.key == key:
            return latched.top, latched.touch
        prev_began, _ = script.turn_bounds_at(max(turn_start - 1, 0))
        if base.let_go is not None and position_ms >= turn_start:
            top = base.let_go
        else:
            top = genau_height(turn_start, prev_began)
        if (latched is not None and latched.key.let_go is None
                and base.let_go is not None):
            # The flip itself: the moment was chosen from the live wave, and
            # the now-frozen one cannot re-answer it — carried.  Every OTHER
            # re-key (the wave realigning after a resume, a control moving the
            # floor) is a real change of plan, and the touch is re-chosen with
            # it — the old wave's touch means nothing on the new one.
            touch = latched.touch
        else:
            touch = park_touch_after(turn_start, prev_began)
        # Never latched off a parked publish before its turn: right after a
        # rewind the publish is still the frozen pre-rewind wave for a beat, so
        # a forecast latched from it would freeze the stale wave's touch.  The
        # live publish arrives within a tick; until then the choice stays a
        # forecast.
        frozen = (position_ms >= turn_start - round(_TOUCH_FREEZE_AHEAD_MS * speed)
                  and (base.let_go is None or position_ms >= turn_start))
        if latch is not None and (frozen or latched is not None):
            # A turn the playhead is this far past can no longer be the
            # boundary in play: the scan is over by then, either on a touch or
            # on the cap it gives up at.
            horizon = round((PARK_TOUCH_WAIT_CAP_MS + _TOUCH_LAG_MS) * speed)
            latch.remember(turn_start, DescentChoice(key, top, touch),
                           stale_before=position_ms - horizon)
        return top, touch

    def at(sample_ms: int, planned: float) -> tuple[float, str]:
        """One sample of the line: how high, and whose stretch it is in."""
        if script.is_resting_at(sample_ms):
            # Genau's stretch.  It opens with the climb out of the park.
            if stroke is None:
                # Nobody is going to take these stretches: in Nau's own mode
                # there is no Genau behind the screen, and the script's driver
                # rests the device through them.
                return 0.0, DRIVEN_BY_NOTHING
            began, ends_at = script.turn_bounds_at(sample_ms)
            if began is not None and climb_ms:
                since = sample_ms - began
                if since < climb_ms:
                    # The climb: park up to wherever the resumed stroke opens.
                    # Genau holds its swing through it, so it costs no stroke.
                    top = stroke_at(resume_base)
                    return top * max(0, since) / climb_ms, DRIVEN_BY_NEUTRAL
            value = genau_height(sample_ms, began)
            feather_ms = round(_SEAM_FEATHER_MS * speed)
            if ends_at is not None and ends_at - sample_ms < feather_ms:
                seam_top, seam_touch = descent_entry(ends_at)
                if seam_touch is None:
                    # Eased onto the ramp's latched top so the join cannot
                    # flicker — see _SEAM_FEATHER_MS.
                    weight = 1 - (ends_at - sample_ms) / feather_ms
                    value = value * (1 - weight) + seam_top * weight
            return value, DRIVEN_BY_GENAU
        # The script's stretch — opening with the blue's exit.  A stroke whose
        # floor rests on the park needs no ramp: the blue swings on past the
        # boundary to its touch-down and the gray runs flat from there — his
        # rule, and where the arbiter really sets the device down.  A raised
        # floor ramps down from wherever the blue leaves the device.
        turn_start, _turn_end = script.turn_bounds_at(sample_ms)
        if turn_start is not None and stroke is not None:
            top, touch = descent_entry(turn_start)
            if touch is not None:
                if sample_ms <= touch and base.let_go is None:
                    # The extension belongs to the stretch ENDING here, not to
                    # the script turn these samples sit inside — and it is only
                    # drawn while Genau really still has the device.  Off a
                    # parked publish (a rewind landing just past a boundary) it
                    # would be a stroke nobody is making, re-anchoring under
                    # the playhead into a cliff.
                    prev_began, _ = script.turn_bounds_at(max(turn_start - 1, 0))
                    value = genau_height(sample_ms, prev_began)
                    feather_ms = round(_SEAM_FEATHER_MS * speed)
                    if touch - sample_ms < feather_ms:
                        # Eased onto the park it is about to touch, so the join
                        # with the flat gray cannot flicker.
                        weight = 1 - (touch - sample_ms) / feather_ms
                        value = value * (1 - weight)
                    return value, DRIVEN_BY_GENAU
            else:
                since = sample_ms - turn_start
                if since < ramp_ms:
                    return top * (1 - max(0, since) / ramp_ms), DRIVEN_BY_NEUTRAL
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
    # dot can never ride a line that is not there.  Keyed on the console's osr2
    # instead it would sit on Genau's frozen position over a gray ramp at every
    # handoff, for as long as the console lags the arbiter.
    height, who_now = at(position_ms, script.planned_position_at(position_ms) / 100)
    if who_now == DRIVEN_BY_GENAU:
        marker = base.position
    else:
        marker = round(height * POSITION_MAX)
    return replace(
        base,
        # Who has the device AT THE PLAYHEAD, from the same function that drew
        # the line under the dot — the console's pill reads this, so the pill
        # and the line cannot disagree.  The round-tripped osr2 state flips at
        # the arbiter's decision, seconds before the dot finishes riding the
        # blue it is still drawn on.
        driven=who_now,
        waveform=tuple(values),
        slide=slide,
        edge=edge,
        # Always said, even for a single run: the painter's fallback color for
        # an empty ``segments`` is the OSR2 state, and that state trails the
        # arbiter by a beat at every handoff, so an empty one would flash the
        # script's green over the whole stroke as the device changes hands.
        # The marks are stable while the picture is, so the readout still
        # compares equal to itself between repaints.
        segments=tuple(marks),
        position=marker,
    )
