"""The trace's model: what the device is about to be asked to do, and by whom.

Three colors, and each means one thing.  Green is the funscript actually
scripting, blue is Genau actually stroking, and light grey is the buffer
between them — the glide down onto the park, the wait there, and the climb back
up to the stroke's floor.  Nobody is driving through a ramp; the device is being
handed over, so the ramps are the buffer's grey.
"""
from __future__ import annotations

import numpy as np
from player_core.funscript import PARK_SETTLE_MS, Funscript

from player_core.drive_readout import (
    DRIVEN_BY_FUNSCRIPT,
    DRIVEN_BY_GENAU,
    DRIVEN_BY_NEUTRAL,
    DRIVEN_BY_NOTHING,
    POSITION_MAX,
    TAKEOVER_RISE_MS,
    TRACE_SAMPLES,
    DriveHud,
)
from nau.drive_trace import drive_readout

# A 7.9-second trace: 79 steps of a round 100ms each, so a whole-step slide in
# these tests is exact tuple equality rather than a hair of interpolation.
SPAN_S = 7.9
STEP_MS = 100


def _stroke(**over) -> DriveHud:
    """Genau's readout as it publishes it: its own stroke, forward from now.

    Amplitude 80 around centre 50, so the stroke's floor is at 10% — above the
    park, which is the case that has ramps.
    """
    base = dict(
        speed=50, amplitude=80, center=50, trace_seconds=SPAN_S,
        waveform=tuple(0.5 + 0.4 * np.sin(i / 6) for i in range(TRACE_SAMPLES)))
    base.update(over)
    return DriveHud(**base)


def _parked_stroke(**over) -> DriveHud:
    """The same stroke as a *parked* Genau publishes it: rested at the foot of
    its swing, so sample 0 is its floor and the wave climbs from there — which
    is what the stroke waiting through a funscript's turn looks like."""
    return _stroke(
        waveform=tuple(0.5 - 0.4 * np.cos(i / 6) for i in range(TRACE_SAMPLES)),
        **over)


def _script(*, until_ms: int) -> Funscript:
    """A script that strokes hard for *until_ms* and then stops for good.

    Densely sampled while it runs, so ``is_resting_at`` reads it as real action,
    and nothing at all after — which is the shape of a scripted segment ending
    mid-video, the moment the handoff is about.
    """
    return Funscript(actions=[(t, 0 if (t // 200) % 2 else 100)
                              for t in range(0, until_ms + 1, 200)])


def _peaking_stroke(*, at_ms: int, **over) -> DriveHud:
    """A stroke at the top of its swing *at_ms* into the window, so its next
    floor-touch is most of a cycle later — the case where the arbiter really
    does hold the handoff past the rest's own end."""
    peak = at_ms / STEP_MS
    return _stroke(
        waveform=tuple(0.5 + 0.4 * np.cos((i - peak) / 6)
                       for i in range(TRACE_SAMPLES)),
        **over)


def _script_ahead(*, from_ms: int = 8_000, to_ms: int = 9_000) -> Funscript:
    """A script whose one cluster is still ahead of the playhead — the other
    seam, where Genau is driving now and hands over inside the window."""
    return Funscript(actions=[(t, 0 if (t // 200) % 2 else 100)
                              for t in range(from_ms, to_ms + 1, 200)])


def _read(script, *, at: int, published=None, genau_behind=True,
          osr2_has_script=True, script_took_over_ms=None) -> DriveHud:
    return drive_readout(
        published if published is not None else _stroke(),
        script=script, position_ms=at, genau_behind=genau_behind,
        osr2_has_script=osr2_has_script,
        script_took_over_ms=script_took_over_ms)


def _colors(hud: DriveHud) -> list[str]:
    return [who for _start, _end, who in hud.runs]


class TestOneLineTwoDrivers:
    """The span runs forward from the playhead, so a handoff that has not happened
    yet is inside it — which is the only way to see the seam on its way in rather
    than after it is over."""

    def test_a_script_running_the_whole_span_is_all_its_own(self):
        script = _script(until_ms=120_000)

        hud = _read(script, at=0)

        assert hud.segments == ((0, DRIVEN_BY_FUNSCRIPT),)
        assert hud.waveform == script.planned_trace(0, round(SPAN_S * 1000), TRACE_SAMPLES)

    def test_the_end_of_a_scripted_stretch_hands_over_through_the_buffer(self):
        """Green for what is left of the script, grey for the buffer that
        belongs to neither driver, blue for the stroke waiting — one line across
        both joins."""
        hud = _read(_script(until_ms=2_000), at=1_000)

        assert _colors(hud) == [
            DRIVEN_BY_FUNSCRIPT, DRIVEN_BY_NEUTRAL, DRIVEN_BY_GENAU]

    def test_the_runs_touch_so_the_line_never_breaks_at_the_joins(self):
        hud = _read(_script(until_ms=2_000), at=1_000)

        for left, right in zip(hud.runs, hud.runs[1:]):
            assert left[1] == right[0]

    def test_a_script_about_to_start_up_shows_the_stroke_handing_over(self):
        """The seam runs both ways, and the trace sees this one coming too: the
        stroke Genau is sending now, the buffer it hands into, then the script
        rising to meet its opening action at the span's far edge."""
        hud = _read(_script_ahead(), at=0, osr2_has_script=False)

        assert _colors(hud) == [
            DRIVEN_BY_GENAU, DRIVEN_BY_NEUTRAL, DRIVEN_BY_FUNSCRIPT]

    def test_in_nau_the_gap_is_nobody_s_and_rests_on_the_floor(self):
        """No Genau behind that screen, and the script's own driver rests the
        device — so past the buffer the picture is the park, not a stroke that
        is not coming."""
        hud = drive_readout(
            None, script=_script(until_ms=2_000), position_ms=0,
            genau_behind=False, osr2_has_script=True)
        gap_start = hud.runs[-1][0]

        assert _colors(hud) == [
            DRIVEN_BY_FUNSCRIPT, DRIVEN_BY_NEUTRAL, DRIVEN_BY_NOTHING]
        assert set(hud.waveform[gap_start:]) == {0.0}


class TestTheBufferBetweenThem:
    """The buffer is a shape, not a gap: down from the floor, flat on the park,
    up to the floor again — and all of it grey, because through it the device
    belongs to neither driver."""

    def test_genau_s_blue_ends_on_the_floor_and_the_grey_takes_it_down(self):
        hud = _read(_script_ahead(), at=0, osr2_has_script=False)
        blue_end = hud.runs[0][1]

        assert hud.waveform[blue_end] <= 0.16          # the floor, touched
        descent = hud.waveform[blue_end:blue_end + 5]
        for left, right in zip(descent, descent[1:]):
            assert right < left
        assert hud.runs[1][2] == DRIVEN_BY_NEUTRAL     # the descent is the buffer's

    def test_the_descent_lands_on_the_park_and_waits_there(self):
        hud = _read(_script_ahead(), at=0, osr2_has_script=False)
        blue_end = hud.runs[0][1]
        settled = blue_end + round(PARK_SETTLE_MS / STEP_MS)
        rise_start = hud.runs[2][0]

        assert set(hud.waveform[settled:rise_start - 1]) == {0.0}

    def test_the_buffer_climbs_back_to_the_floor_before_the_stroke_resumes(self):
        published = _parked_stroke()
        hud = _read(_script(until_ms=2_000), at=1_000, published=published)
        blue_start = hud.runs[-1][0]
        climb = round(TAKEOVER_RISE_MS / STEP_MS)

        assert hud.waveform[blue_start - climb] == 0.0        # off the park...
        rising = hud.waveform[blue_start - climb:blue_start]
        for left, right in zip(rising, rising[1:]):
            assert right > left                               # ...climbing...
        assert hud.waveform[blue_start] == published.waveform[0]   # ...to the floor

    def test_the_climb_is_the_buffer_s_grey_not_genau_s_blue(self):
        hud = _read(_script(until_ms=2_000), at=1_000, published=_parked_stroke())

        assert hud.runs[-2][2] == DRIVEN_BY_NEUTRAL

    def test_the_climb_spends_no_stroke(self):
        """The swing holds while the device rises to meet it, so the wave after
        the climb is the whole published stroke — not one with its opening
        samples eaten by the ramp."""
        published = _parked_stroke()
        hud = _read(_script(until_ms=2_000), at=1_000, published=published)
        blue_start = hud.runs[-1][0]

        assert (hud.waveform[blue_start:]
                == published.waveform[:TRACE_SAMPLES - blue_start])

    def test_at_full_amplitude_there_is_no_ramp_at_either_end(self):
        """His rule: a stroke whose floor already rests on the park has nothing
        to ramp across.  The grey begins right at the touch-down, and the stroke
        resumes straight out of the park."""
        published = _stroke(
            amplitude=100,
            waveform=tuple(0.5 + 0.5 * np.sin(i / 3) for i in range(TRACE_SAMPLES)))

        ending = _read(_script_ahead(), at=0, published=published,
                       osr2_has_script=False)
        blue_end = ending.runs[0][1]
        resuming = _read(_script(until_ms=2_000), at=1_000,
                         published=_stroke(amplitude=100))
        blue_start = resuming.runs[-1][0]

        assert ending.waveform[blue_end] <= 0.06       # blue rode down to the park
        assert set(ending.waveform[blue_end + 1:ending.runs[2][0]]) == {0.0}
        assert resuming.waveform[blue_start - 1] == 0.0    # grey right up to the seam


class TestGenauSTurnEndsOnItsFloor:
    """The arbiter holds the handoff until Genau's stroke comes down onto its
    floor, so the blue runs past the rest's own end to that touch — and the
    picture has to end it in the same place, at the same moment, every frame."""

    def test_the_blue_runs_past_the_rest_s_end_to_the_touch(self):
        rest_ends_at = 8_000 - 5_000                   # the cluster's lead-in opens
        published = _peaking_stroke(at_ms=rest_ends_at)

        hud = _read(_script_ahead(), at=0, published=published,
                    osr2_has_script=False)

        assert hud.runs[0][1] * STEP_MS > rest_ends_at
        assert hud.waveform[hud.runs[0][1]] <= 0.16    # and ends on the floor

    def test_where_it_ends_holds_still_as_the_picture_slides(self):
        """The stroke is re-rendered from a moving phase every publish, so
        "the first sample under the floor" lands a sample earlier or later frame
        to frame.  Pinned to that, the end of the blue jittered half a sample
        back and forth — the stutter he watched, on the one stretch of line that
        was supposed to be gliding."""
        script = _script_ahead()

        ends = set()
        for playhead in range(0, 3 * STEP_MS, 40):
            hud = _read(script, at=playhead, osr2_has_script=False)
            anchor = playhead - playhead % 40 - hud.slide * STEP_MS
            ends.add(round(anchor + hud.runs[0][1] * STEP_MS))

        assert max(ends) - min(ends) <= 1

    def test_nothing_jumps_when_the_console_catches_up(self):
        """The moment the arbiter's flip lands, the picture must be the picture
        it already was: the blue ends at the touch either way.  Drawn one way
        before the flip and another after, the last of the blue vanished
        mid-slide — which is what he kept seeing."""
        script = _script_ahead()
        published = _parked_stroke()      # sample 0 already on the floor: the touch is now
        at = 4_000                        # past the rest's end, so the arbiter is flipping

        before = _read(script, at=at, published=published, osr2_has_script=False)
        after = _read(script, at=at, published=published, osr2_has_script=True,
                      script_took_over_ms=at)

        assert _colors(before) == _colors(after)
        assert max(abs(b - a) for b, a in zip(before.waveform, after.waveform)) < 0.01

    def test_a_stroke_that_never_comes_down_hands_over_at_the_cap(self):
        """A stroke crawling so slowly it does not reach its floor inside the
        window would otherwise hold the script off for good; the arbiter gives
        up after the cap, and the picture ends the blue where the wait does."""
        never = _stroke(waveform=tuple(0.9 for _ in range(TRACE_SAMPLES)))

        hud = _read(_script_ahead(), at=0, published=never, osr2_has_script=False)

        assert _colors(hud)[0] == DRIVEN_BY_GENAU
        assert hud.runs[0][1] < TRACE_SAMPLES - 1      # it does end


class TestStillPicture:
    """He watched the line boil: resampled from the playhead every frame, every
    peak landed somewhere slightly different."""

    def test_the_shape_slides_along_rather_than_being_redrawn(self):
        script = _script(until_ms=120_000)

        first = _read(script, at=0).waveform
        later = _read(script, at=2 * STEP_MS).waveform

        assert later[:-2] == first[2:]

    def test_the_whole_handoff_slides_rigidly_too(self):
        """Not just the scripted stretch: the buffer, both its ramps and the
        stroke behind them move together, as one picture."""
        script = _script(until_ms=2_000)
        published = _parked_stroke()

        first = _read(script, at=0, published=published).waveform
        later = _read(script, at=2 * STEP_MS, published=published).waveform

        assert later[:-2] == first[2:]

    def test_a_playhead_between_two_samples_slides_the_stable_picture(self):
        """The script never changes while it plays, so the picture is computed
        once and only slid: between two knots the *values* stay exactly the
        knot-behind's — blending them morphed the wave's shape at fixed columns
        every frame, the regression he caught — and the leftover fraction rides
        along for the painter to shift the whole line by."""
        script = _script(until_ms=120_000)

        at_knot = _read(script, at=0)
        between = _read(script, at=40)

        assert between.waveform == at_knot.waveform
        assert at_knot.slide == 0.0
        assert between.slide == 0.4


class TestPositionMarker:
    def test_a_script_driving_puts_the_marker_where_the_plan_has_the_device(self):
        script = _script(until_ms=120_000)

        hud = _read(script, at=400)

        assert hud.position == round(
            script.planned_position_at(400) / 100 * POSITION_MAX)

    def test_a_script_holding_the_device_parked_rests_the_marker_on_the_park(self):
        """Through the buffer the device sits at its park; a marker riding the
        script's interpolated line floated where nothing was."""
        script = _script(until_ms=2_000)

        hud = _read(script, at=5_000)  # in the tail: parked, not yet resting

        assert hud.position == 0

    def test_the_dot_glides_down_with_the_device_after_the_handoff(self):
        """The driver settles the device onto the park over half a second; a dot
        that teleported to the park while the OSR2 was easing down called the
        picture a liar.  The glide opens at the stroke's floor (10% here), and
        it is anchored at the flip the console recorded — the moment the pause
        really landed."""
        script = _script_ahead()

        at_handoff = _read(script, at=3_000, script_took_over_ms=3_000)
        mid_settle = _read(script, at=3_240, script_took_over_ms=3_000)
        settled = _read(script, at=3_600, script_took_over_ms=3_000)

        assert at_handoff.position == 1000
        assert settled.position == 0
        assert settled.position < mid_settle.position < at_handoff.position

    def test_genau_driving_leaves_the_marker_where_genau_published_it(self):
        """It is Genau's device then, and Genau knows where it put it — at its
        own rate, rather than at the line's nearest knot."""
        published = _stroke(position=1234)

        hud = _read(_script(until_ms=120_000), at=0, published=published,
                    osr2_has_script=False)

        assert hud.position == 1234


class TestNothingToFoldIn:
    def test_an_unscripted_video_leaves_the_readout_alone(self):
        published = _stroke()

        assert drive_readout(published, script=None, position_ms=0,
                             genau_behind=True, osr2_has_script=False) == published

    def test_a_single_run_still_names_its_driver(self):
        """The painter's fallback color for empty segments is the OSR2 state,
        which trails the arbiter by a beat at every handoff — the whole stroke
        flashed the script's green for a frame each time the device changed
        hands.  Named by the model itself, the color cannot lag."""
        hud = _read(_script(until_ms=120_000), at=0)

        assert hud.segments == ((0, DRIVEN_BY_FUNSCRIPT),)

    def test_an_unchanging_picture_still_compares_equal_to_itself(self):
        """Or the panel is repainted per frame for a difference only in how the
        same picture was described."""
        script = _script(until_ms=120_000)

        assert _read(script, at=0) == _read(script, at=0)
