"""The trace's model: what the device is about to be asked to do, and by whom."""
from __future__ import annotations

import numpy as np
from player_core.funscript import Funscript

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


def _stroke(**over) -> DriveHud:
    """Genau's readout as it publishes it: its own stroke, forward from now."""
    base = dict(
        speed=50, amplitude=80, center=50, trace_seconds=SPAN_S,
        waveform=tuple(0.5 + 0.4 * np.sin(i / 6) for i in range(TRACE_SAMPLES)))
    base.update(over)
    return DriveHud(**base)


def _script(*, until_ms: int) -> Funscript:
    """A script that strokes hard for *until_ms* and then stops for good.

    Densely sampled while it runs, so ``is_resting_at`` reads it as real action,
    and nothing at all after — which is the shape of a scripted segment ending
    mid-video, the moment the handoff is about.
    """
    return Funscript(actions=[(t, 0 if (t // 200) % 2 else 100)
                              for t in range(0, until_ms + 1, 200)])


def _read(script, *, at: int, published=None, genau_behind=True,
          osr2_has_script=True) -> DriveHud:
    return drive_readout(
        published if published is not None else _stroke(),
        script=script, position_ms=at, genau_behind=genau_behind,
        osr2_has_script=osr2_has_script)


class TestOneLineTwoDrivers:
    """The span runs forward from the playhead, so a handoff that has not happened
    yet is inside it — which is the only way to see the seam on its way in rather
    than after it is over.  Between the drivers sits the neutral buffer, drawn in
    neither one's color: the device rests at its park there."""

    def test_a_script_running_the_whole_span_is_all_its_own(self):
        script = _script(until_ms=120_000)

        hud = _read(script, at=0)

        assert hud.segments == ((0, DRIVEN_BY_FUNSCRIPT),)
        assert hud.waveform == script.planned_trace(0, round(SPAN_S * 1000), TRACE_SAMPLES)

    def test_the_end_of_a_scripted_stretch_hands_over_through_the_neutral_buffer(self):
        """Green for what is left of the script, light grey for the parked buffer
        that belongs to neither driver, blue for the stroke waiting — one line
        across both joins."""
        hud = _read(_script(until_ms=2_000), at=0)

        assert [who for _start, _end, who in hud.runs] == [
            DRIVEN_BY_FUNSCRIPT, DRIVEN_BY_NEUTRAL, DRIVEN_BY_GENAU]

    def test_the_runs_touch_so_the_line_never_breaks_at_the_joins(self):
        hud = _read(_script(until_ms=2_000), at=0)

        for left, right in zip(hud.runs, hud.runs[1:]):
            assert left[1] == right[0]

    def test_the_stroke_side_is_genau_s_own_samples_run_from_the_seam(self):
        """Not the script's last position held flat: what the device will be
        doing after the handoff is the stroke Genau is parked on, run from the
        moment it resumes — its opening samples pinned to the seam.  Read by
        screen position instead, the stroke sat still while the seam swept over
        it: revealed, not approaching."""
        published = _stroke()
        hud = _read(_script(until_ms=2_000), at=0, published=published)
        seam = hud.runs[-1][0]

        assert hud.waveform[seam + 1:] == published.waveform[1:TRACE_SAMPLES - seam]

    def test_the_stroke_after_the_seam_begins_where_the_buffer_rests(self):
        """The device is wherever the plan leaves it when Genau takes over — its
        park, once the buffer has wound down — and the takeover glide walks it
        onto the stroke from there, so the blue starts at that resting height
        rather than jumping to the stroke's."""
        script = _script(until_ms=2_000)

        hud = _read(script, at=0)
        seam = hud.runs[-1][0]

        planned = script.planned_trace(0, round(SPAN_S * 1000), TRACE_SAMPLES)
        assert hud.waveform[seam] == planned[seam]

    def test_the_waiting_stroke_slides_left_with_the_seam(self):
        """He watched the interval between the green's end and the blue's start
        change frame to frame.  Anchored to the seam, the whole line — the
        script, the buffer, the joins, the stroke waiting behind them — slides
        left together.  Two whole steps, which the slide quantum divides."""
        script = _script(until_ms=2_000)
        step_ms = round(SPAN_S * 1000 / (TRACE_SAMPLES - 1))

        first = _read(script, at=0).waveform
        later = _read(script, at=2 * step_ms).waveform

        assert later[:-2] == first[2:]

    def test_a_script_about_to_start_up_shows_the_stroke_handing_over(self):
        """The seam runs both ways, and the trace sees this one coming too: the
        stroke Genau is sending now, the neutral buffer it hands into, then the
        script rising to meet its opening action at the span's far edge."""
        script = Funscript(actions=[(t, 0 if (t // 200) % 2 else 100)
                                    for t in range(8_000, 9_001, 200)])

        hud = _read(script, at=0, osr2_has_script=False)

        assert [who for _s, _e, who in hud.runs] == [
            DRIVEN_BY_GENAU, DRIVEN_BY_NEUTRAL, DRIVEN_BY_FUNSCRIPT]

    def test_genau_s_turn_ends_in_a_blue_glide_that_lands_on_the_park(self):
        """The blue runs past the rest's end to the stroke's next floor-touch —
        the arbiter really does hold the handoff for it — and the settle down
        to the park is Genau's blue too; the grey begins only on the park."""
        published = _stroke()  # amplitude 80: floor at 10%
        script = Funscript(actions=[(t, 0 if (t // 200) % 2 else 100)
                                    for t in range(8_000, 9_001, 200)])

        hud = _read(script, at=0, published=published, osr2_has_script=False)
        blue_run = hud.runs[0]

        assert [who for _s, _e, who in hud.runs] == [
            DRIVEN_BY_GENAU, DRIVEN_BY_NEUTRAL, DRIVEN_BY_FUNSCRIPT]
        # The touch lands just past the handoff knot at 30, at the floor.
        assert hud.waveform[30] <= 0.12
        # The settle then walks down from the floor to the park, still blue.
        assert hud.waveform[31] < hud.waveform[30]
        assert hud.waveform[32] < hud.waveform[31]
        # The grey's own first sample is the park itself, nothing higher.
        assert hud.waveform[blue_run[1]] == 0.0

    def test_at_full_amplitude_the_grey_takes_over_right_at_the_floor_touch(self):
        """His rule: a stroke already touching the park needs no settle ramp at
        all — the blue swings on to its touch-down and the grey flatline begins
        there, not a sample higher."""
        # A slow wave whose next floor-touch past the handoff knot at 30 falls
        # near sample 32 under the shared touch tolerance.
        published = _stroke(
            amplitude=100,
            waveform=tuple(0.5 + 0.5 * np.sin(i / 3) for i in range(TRACE_SAMPLES)))
        script = Funscript(actions=[(t, 0 if (t // 200) % 2 else 100)
                                    for t in range(8_000, 9_001, 200)])

        hud = _read(script, at=0, published=published, osr2_has_script=False)

        assert [who for _s, _e, who in hud.runs] == [
            DRIVEN_BY_GENAU, DRIVEN_BY_NEUTRAL, DRIVEN_BY_FUNSCRIPT]
        grey_start = hud.runs[1][0]
        assert grey_start == 33                  # right after the touch-down...
        assert hud.waveform[32] <= 0.06          # ...which is on the park
        rise_start = hud.runs[2][0]
        assert set(hud.waveform[grey_start:rise_start]) == {0.0}

    def test_below_full_amplitude_the_settle_opens_at_the_floor_touch(self):
        """The raised floor's touch, wherever the wave puts it — and from that
        touch the blue glides down to the park before the grey begins."""
        published = _stroke(  # amplitude 80: floor at 10%
            waveform=tuple(0.5 + 0.4 * np.sin(i / 3) for i in range(TRACE_SAMPLES)))
        script = Funscript(actions=[(t, 0 if (t // 200) % 2 else 100)
                                    for t in range(8_000, 9_001, 200)])

        hud = _read(script, at=0, published=published, osr2_has_script=False)

        # The touch near sample 32, then the settle samples down to the park.
        assert hud.waveform[32] <= 0.16
        for index in range(33, 36):
            assert hud.waveform[index + 1] < hud.waveform[index]
        assert hud.runs[0][1] >= 37              # the settle is still Genau's blue
        assert hud.waveform[hud.runs[0][1]] == 0.0

    def test_a_playhead_inside_the_buffer_keeps_the_blue_until_the_touch(self):
        """Once the playhead crosses the rest's end, the boundary scrolls off
        the window's left edge — but the arbiter is still holding the handoff
        for the stroke's touch, so the leading stretch is still Genau's blue,
        running to its touch-down.  Going grey the moment the rest ended wiped
        up to a full cycle of blue the device was still going to stroke."""
        published = _stroke(
            amplitude=100,
            waveform=tuple(0.5 + 0.5 * np.sin(i / 3) for i in range(TRACE_SAMPLES)))
        script = Funscript(actions=[(t, 0 if (t // 200) % 2 else 100)
                                    for t in range(8_000, 9_001, 200)])

        hud = _read(script, at=4_000, published=published, osr2_has_script=False)

        # Blue lead, grey to the rise, the cluster's green, the tail's grey.
        assert [who for _s, _e, who in hud.runs] == [
            DRIVEN_BY_GENAU, DRIVEN_BY_NEUTRAL, DRIVEN_BY_FUNSCRIPT,
            DRIVEN_BY_NEUTRAL]
        touch = hud.runs[0][1]
        assert hud.waveform[touch - 1] <= 0.06   # blue rode the wave to its floor
        rise_start = hud.runs[2][0]
        assert set(hud.waveform[touch:rise_start]) == {0.0}

    def test_once_the_script_has_the_device_the_leading_buffer_is_grey(self):
        """The same spot after the arbiter flips: the pause landed on the
        touch, so nothing blue is left ahead of the playhead."""
        published = _stroke(
            amplitude=100,
            waveform=tuple(0.5 + 0.5 * np.sin(i / 3) for i in range(TRACE_SAMPLES)))
        script = Funscript(actions=[(t, 0 if (t // 200) % 2 else 100)
                                    for t in range(8_000, 9_001, 200)])

        hud = _read(script, at=4_000, published=published, osr2_has_script=True)

        assert [who for _s, _e, who in hud.runs] == [
            DRIVEN_BY_NEUTRAL, DRIVEN_BY_FUNSCRIPT, DRIVEN_BY_NEUTRAL]

    def test_the_dot_glides_down_with_the_device_after_the_handoff(self):
        """The driver settles the device onto the park over half a second; a
        dot that teleported to the floor while the OSR2 was easing down called
        the picture a liar.  The glide opens at the stroke's floor (10% for
        center 50, amplitude 80) — not at whatever the published position
        happens to be — so it descends the same way every frame."""
        published = _stroke(position=5000)
        script = Funscript(actions=[(t, 0 if (t // 200) % 2 else 100)
                                    for t in range(8_000, 9_001, 200)])

        at_handoff = _read(script, at=3_000, published=published)
        mid_settle = _read(script, at=3_240, published=published)
        settled = _read(script, at=3_600, published=published)

        assert at_handoff.position == 1000
        assert settled.position == 0
        assert settled.position < mid_settle.position < at_handoff.position

    def test_in_nau_the_gap_is_nobody_s_and_rests_on_the_floor(self):
        """No Genau behind that screen, and the script's own driver rests the
        device — so past the buffer the picture is the floor, not a stroke that
        is not coming."""
        hud = drive_readout(
            None, script=_script(until_ms=2_000), position_ms=0,
            genau_behind=False, osr2_has_script=True)
        gap_start = hud.runs[-1][0]

        assert [who for _s, _e, who in hud.runs] == [
            DRIVEN_BY_FUNSCRIPT, DRIVEN_BY_NEUTRAL, DRIVEN_BY_NOTHING]
        assert set(hud.waveform[gap_start + 1:]) == {0.0}


class TestStillPicture:
    """He watched the line boil: resampled from the playhead every frame, every
    peak landed somewhere slightly different."""

    def test_the_shape_slides_along_rather_than_being_redrawn(self):
        script = _script(until_ms=120_000)
        step_ms = round(SPAN_S * 1000 / (TRACE_SAMPLES - 1))

        first = _read(script, at=0).waveform
        later = _read(script, at=2 * step_ms).waveform

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
        """Through the handed-over buffer the device sits at its park; a marker
        riding the script's interpolated line floated where nothing was."""
        script = _script(until_ms=2_000)

        hud = _read(script, at=5_000)  # in the tail: parked, not yet resting

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
