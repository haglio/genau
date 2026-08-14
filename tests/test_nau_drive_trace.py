"""The trace's model: what the device is about to be asked to do, and by whom.

The line is four things in a row — whatever Genau is doing, a ramp down onto
the park, whatever the funscript is doing, a ramp back up to the stroke — and
each colour means one thing: green is the script scripting, blue is Genau
stroking, grey is a ramp or the rest between them, because through those the
device belongs to neither driver.
"""
from __future__ import annotations

import numpy as np
from player_core.funscript import HANDOFF_RAMP_MS, Funscript

from player_core.drive_readout import (
    DRIVEN_BY_FUNSCRIPT,
    DRIVEN_BY_GENAU,
    DRIVEN_BY_NEUTRAL,
    DRIVEN_BY_NOTHING,
    POSITION_MAX,
    TRACE_SAMPLES,
    DriveHud,
)
from nau.drive_trace import drive_readout

# A 7.9-second trace: 79 steps of a round 100ms each, so a whole-step slide in
# these tests is exact tuple equality rather than a hair of interpolation.
SPAN_S = 7.9
STEP_MS = 100
RAMP_STEPS = HANDOFF_RAMP_MS // STEP_MS


def _stroke(**over) -> DriveHud:
    """Genau's readout as it publishes it: its own stroke, forward from now.

    Amplitude 80 around centre 50, so the stroke's floor is at 10% — above the
    park, which is the case where the ramps have somewhere to go.
    """
    base = dict(
        speed=50, amplitude=80, center=50, trace_seconds=SPAN_S,
        waveform=tuple(0.5 + 0.4 * np.sin(i / 6) for i in range(TRACE_SAMPLES)))
    base.update(over)
    return DriveHud(**base)


def _stroke_at(ms: int, **over) -> DriveHud:
    """The stroke as Genau publishes it *ms* into the video: the same wave, its
    phase advanced by however many samples have gone by.  A published readout is
    a window forward from now, so it moves on its own — which is why the painter
    leaves the live run unshifted, and why a fixture that held it still could not
    show the picture sliding."""
    steps = ms // STEP_MS
    return _stroke(
        waveform=tuple(0.5 + 0.4 * np.sin((i + steps) / 6)
                       for i in range(TRACE_SAMPLES)),
        **over)


def _parked_stroke(**over) -> DriveHud:
    """The same stroke as a *parked* Genau publishes it: rested at the foot of
    its swing, so sample 0 is its floor and the wave climbs from there — which
    is what the stroke waiting through a funscript's turn looks like."""
    return _stroke(
        waveform=tuple(0.5 - 0.4 * np.cos(i / 6) for i in range(TRACE_SAMPLES)),
        **over)


def _script(*, until_ms: int) -> Funscript:
    """A script that strokes hard for *until_ms* and then stops for good."""
    return Funscript(actions=[(t, 0 if (t // 200) % 2 else 100)
                              for t in range(0, until_ms + 1, 200)])


def _script_ahead(*, from_ms: int = 8_000, to_ms: int = 9_000) -> Funscript:
    """A script whose one cluster is still ahead of the playhead — the seam
    where Genau is driving now and hands over inside the window."""
    return Funscript(actions=[(t, 0 if (t // 200) % 2 else 100)
                              for t in range(from_ms, to_ms + 1, 200)])


def _read(script, *, at: int, published=None, genau_behind=True,
          osr2_has_script=True, let_go_at=None) -> DriveHud:
    return drive_readout(
        published if published is not None else _stroke(),
        script=script, position_ms=at, genau_behind=genau_behind,
        osr2_has_script=osr2_has_script, let_go_at=let_go_at)


def _colors(hud: DriveHud) -> list[str]:
    return [who for _start, _end, who in hud.runs]


class TestOneLineTwoDrivers:
    """The span runs forward from the playhead, so a handoff that has not
    happened yet is inside it — which is the only way to see a seam on its way
    in rather than after it is over."""

    def test_a_script_running_the_whole_span_is_all_its_own(self):
        script = _script(until_ms=120_000)

        hud = _read(script, at=0)

        assert hud.segments == ((0, DRIVEN_BY_FUNSCRIPT),)
        assert hud.waveform == script.planned_trace(
            0, round(SPAN_S * 1000), TRACE_SAMPLES)

    def test_the_end_of_a_scripted_stretch_hands_over_through_the_buffer(self):
        """Green while the script runs, grey for the buffer that belongs to
        neither driver, blue for the stroke waiting behind it."""
        hud = _read(_script(until_ms=2_000), at=1_000)

        assert _colors(hud) == [
            DRIVEN_BY_FUNSCRIPT, DRIVEN_BY_NEUTRAL, DRIVEN_BY_GENAU]

    def test_a_script_about_to_start_up_shows_the_stroke_handing_over(self):
        hud = _read(_script_ahead(), at=0, osr2_has_script=False)

        assert _colors(hud) == [
            DRIVEN_BY_GENAU, DRIVEN_BY_NEUTRAL, DRIVEN_BY_FUNSCRIPT]

    def test_the_runs_touch_so_the_line_never_breaks_at_the_joins(self):
        hud = _read(_script(until_ms=2_000), at=1_000)

        for left, right in zip(hud.runs, hud.runs[1:]):
            assert left[1] == right[0]

    def test_in_nau_the_gap_is_nobody_s_and_rests_on_the_park(self):
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


class TestTheRampDownOntoThePark:
    """Genau's turn ends when the script's turn opens — a time the script fixes
    — and the device walks from wherever that leaves it down onto the park.

    It used to end on the stroke's next floor-touch instead, which only the live
    stroke knew and which moved under the picture every frame: the final cycle
    flickered in and out, and vanished outright at the moment Genau paused and
    its published stroke froze at the floor.
    """

    def test_the_blue_runs_to_the_moment_the_script_turn_opens(self):
        script = _script_ahead()               # its turn opens at 3000ms
        hud = _read(script, at=0, osr2_has_script=False)

        assert hud.runs[0][1] == 3_000 // STEP_MS

    def test_the_ramp_starts_where_the_stroke_was_and_reaches_the_park(self):
        published = _stroke()
        hud = _read(_script_ahead(), at=0, published=published,
                    osr2_has_script=False)
        opens = 3_000 // STEP_MS

        assert hud.waveform[opens] == published.waveform[opens]   # where Genau was
        descent = hud.waveform[opens:opens + RAMP_STEPS + 1]
        for left, right in zip(descent, descent[1:]):
            assert right < left
        assert hud.waveform[opens + RAMP_STEPS] == 0.0            # the park

    def test_the_ramp_is_the_buffer_s_grey_not_genau_s_blue(self):
        hud = _read(_script_ahead(), at=0, osr2_has_script=False)

        assert hud.runs[1][2] == DRIVEN_BY_NEUTRAL

    def test_it_holds_still_as_the_picture_slides(self):
        """Two whole steps on, everything is exactly two columns left — no
        recomputed moment to move under it."""
        script = _script_ahead()

        first = _read(script, at=0, published=_stroke_at(0),
                      osr2_has_script=False).waveform
        later = _read(script, at=2 * STEP_MS, published=_stroke_at(2 * STEP_MS),
                      osr2_has_script=False).waveform

        assert later[:-2] == first[2:]

    def test_the_recorded_handoff_carries_the_ramp_after_the_flip(self):
        """A paused Genau publishes the stroke it will resume with, not where it
        stopped — so the height it let go at is recorded once, and the picture
        goes on drawing the same descent from it."""
        script = _script_ahead()
        before = _read(script, at=2_800, published=_stroke_at(2_800),
                       osr2_has_script=False)
        was_at = float(before.waveform[2])            # the height at 3000ms

        after = _read(script, at=3_000, published=_parked_stroke(),
                      osr2_has_script=True, let_go_at=(3_000, was_at))

        assert after.waveform[0] == was_at            # the descent opens there...
        assert after.waveform[RAMP_STEPS] == 0.0      # ...and still lands on the park

    def test_the_dot_walks_down_the_ramp_with_the_device(self):
        script = _script_ahead()
        published = _parked_stroke()
        args = dict(published=published, osr2_has_script=True,
                    let_go_at=(3_000, 0.8))

        opened = _read(script, at=3_000, **args)
        midway = _read(script, at=3_000 + HANDOFF_RAMP_MS // 2, **args)
        landed = _read(script, at=3_000 + HANDOFF_RAMP_MS, **args)

        assert opened.position == round(0.8 * POSITION_MAX)
        assert landed.position == 0
        assert landed.position < midway.position < opened.position


class TestTheClimbBackOut:
    """The mirror: the script gives the device back a handoff ramp before the
    quiet ends, and Genau walks it up from the park onto its stroke's floor —
    so the stroke begins where it always did, at the far end of the quiet,
    having climbed there across the buffer instead of lunging at the end of it.
    """

    def test_the_buffer_climbs_from_the_park_to_the_floor(self):
        published = _parked_stroke()
        hud = _read(_script(until_ms=2_000), at=1_000, published=published)
        blue_start = hud.runs[-1][0]

        assert hud.waveform[blue_start - RAMP_STEPS] == 0.0
        rising = hud.waveform[blue_start - RAMP_STEPS:blue_start]
        for left, right in zip(rising, rising[1:]):
            assert right > left
        assert hud.waveform[blue_start] == published.waveform[0]

    def test_the_climb_is_the_buffer_s_grey_not_genau_s_blue(self):
        hud = _read(_script(until_ms=2_000), at=1_000, published=_parked_stroke())

        assert hud.runs[-2][2] == DRIVEN_BY_NEUTRAL

    def test_the_climb_spends_no_stroke(self):
        """Genau holds its swing through the climb, so the wave that follows is
        the whole published stroke rather than one with its opening eaten."""
        published = _parked_stroke()
        hud = _read(_script(until_ms=2_000), at=1_000, published=published)
        blue_start = hud.runs[-1][0]

        assert hud.waveform[blue_start:] == published.waveform[:TRACE_SAMPLES - blue_start]

    def test_the_device_rests_on_the_park_before_the_climb(self):
        """The buffer is not all ramp: the script parks the device, it waits,
        and only then climbs."""
        hud = _read(_script(until_ms=2_000), at=1_000, published=_parked_stroke())
        blue_start = hud.runs[-1][0]

        assert hud.waveform[blue_start - RAMP_STEPS - 1] == 0.0

    def test_the_stroke_resumes_at_the_far_end_of_the_quiet(self):
        """Where it always did: the climb lands on it rather than delaying it."""
        script = _script(until_ms=2_000)
        hud = _read(script, at=1_000, published=_parked_stroke())
        blue_start_ms = 1_000 + hud.runs[-1][0] * STEP_MS

        assert blue_start_ms == 2_000 + 5_000


class TestStillPicture:
    """He watched the line boil, twitch and flicker in turn.  Every one of those
    was a value that depended on something other than the playhead."""

    def test_the_shape_slides_along_rather_than_being_redrawn(self):
        script = _script(until_ms=120_000)

        first = _read(script, at=0).waveform
        later = _read(script, at=2 * STEP_MS).waveform

        assert later[:-2] == first[2:]

    def test_the_whole_handoff_slides_rigidly_too(self):
        script = _script(until_ms=2_000)
        published = _parked_stroke()

        first = _read(script, at=1_000, published=published).waveform
        later = _read(script, at=1_000 + 2 * STEP_MS, published=published).waveform

        assert later[:-2] == first[2:]

    def test_a_playhead_between_two_samples_slides_the_stable_picture(self):
        """Between two knots the values stay the knot-behind's — blending them
        morphed the wave's shape at fixed columns every frame — and the leftover
        fraction rides along for the painter to shift the whole line by."""
        script = _script(until_ms=120_000)

        at_knot = _read(script, at=0)
        between = _read(script, at=40)

        assert between.waveform == at_knot.waveform
        assert at_knot.slide == 0.0
        assert between.slide == 0.4

    def test_the_live_stroke_does_not_twitch_between_knots(self):
        """Read at the shifted clock instead of at its column, the live stroke
        rounded up and down as the playhead crossed each half-knot, and the whole
        blue line jumped a sample sideways and back, twice a knot."""
        script = _script_ahead()
        published = _stroke()

        pictures = [_read(script, at=at, published=published,
                          osr2_has_script=False).waveform[:20]
                    for at in (0, 40, 80)]

        assert pictures[0] == pictures[1] == pictures[2]


class TestPositionMarker:
    def test_a_script_driving_puts_the_marker_where_the_plan_has_the_device(self):
        script = _script(until_ms=120_000)

        hud = _read(script, at=400)

        assert hud.position == round(
            script.planned_position_at(400) / 100 * POSITION_MAX)

    def test_a_script_holding_the_device_parked_rests_the_marker_on_the_park(self):
        """Through the lead-in the device sits at its park; a marker riding the
        script's interpolated line floated where nothing was."""
        script = _script_ahead(from_ms=40_000, to_ms=41_000)

        hud = _read(script, at=37_000)

        assert script.is_resting_at(37_000) is False
        assert hud.position == 0

    def test_genau_driving_leaves_the_marker_where_genau_published_it(self):
        """It is Genau's device then, and Genau knows where it put it."""
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
        """The painter's fallback colour for empty segments is the OSR2 state,
        which trails the arbiter by a beat at every handoff — the whole stroke
        flashed the script's green for a frame each time the device changed
        hands.  Named by the model itself, the colour cannot lag."""
        hud = _read(_script(until_ms=120_000), at=0)

        assert hud.segments == ((0, DRIVEN_BY_FUNSCRIPT),)

    def test_an_unchanging_picture_still_compares_equal_to_itself(self):
        script = _script(until_ms=120_000)

        assert _read(script, at=0) == _read(script, at=0)
