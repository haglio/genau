"""The trace's model: what the device is about to be asked to do, and by whom.

The line is four things in a row — whatever Genau is doing, a ramp down onto
the park, whatever the funscript is doing, a ramp back up to the stroke — and
each colour means one thing: green is the script scripting, blue is Genau
stroking, grey is a ramp or the rest between them, because through those the
device belongs to neither driver.

Who holds the device travels inside Genau's own publish: ``let_go`` is None
while Genau strokes and the height it handed over at once it has — the one
number the picture cannot recompute, latched at the source.
"""
from __future__ import annotations

import numpy as np
import pytest
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
    """Genau's readout as a LIVE Genau publishes it: its own stroke, forward
    from now, ``let_go`` unset because it still has the device.

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
    phase advanced by however much time has gone by — a published readout is a
    window forward from now, so it moves on its own."""
    steps = ms / STEP_MS
    return _stroke(
        waveform=tuple(0.5 + 0.4 * np.sin((i + steps) / 6)
                       for i in range(TRACE_SAMPLES)),
        **over)


def _parked_stroke(**over) -> DriveHud:
    """The stroke as a PARKED Genau publishes it, through a funscript's turn:
    rested at the foot of its swing, so sample 0 is its floor (10%) and the
    wave climbs from there.  ``let_go`` says where the device was handed over —
    a real handoff always sets it."""
    over.setdefault("let_go", 0.8)
    over.setdefault(
        "waveform",
        tuple(0.5 - 0.4 * np.cos(i / 6) for i in range(TRACE_SAMPLES)))
    return _stroke(**over)


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
          descent_tops=None) -> DriveHud:
    return drive_readout(
        published if published is not None else _stroke(),
        script=script, position_ms=at, genau_behind=genau_behind,
        descent_tops=descent_tops)


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
        assert hud.waveform == script.planned_trace_window(
            0, round(SPAN_S * 1000), TRACE_SAMPLES)[0][:TRACE_SAMPLES]

    def test_the_end_of_a_scripted_stretch_hands_over_through_the_buffer(self):
        """Green while the script runs, grey for the buffer that belongs to
        neither driver, blue for the stroke waiting behind it."""
        hud = _read(_script(until_ms=2_000), at=1_000,
                    published=_parked_stroke())

        assert _colors(hud) == [
            DRIVEN_BY_FUNSCRIPT, DRIVEN_BY_NEUTRAL, DRIVEN_BY_GENAU]

    def test_a_script_about_to_start_up_shows_the_stroke_handing_over(self):
        hud = _read(_script_ahead(), at=0)

        assert _colors(hud) == [
            DRIVEN_BY_GENAU, DRIVEN_BY_NEUTRAL, DRIVEN_BY_FUNSCRIPT]

    def test_the_runs_touch_so_the_line_never_breaks_at_the_joins(self):
        hud = _read(_script(until_ms=2_000), at=1_000,
                    published=_parked_stroke())

        for left, right in zip(hud.runs, hud.runs[1:]):
            assert left[1] == right[0]

    def test_in_nau_the_gap_is_nobody_s_and_rests_on_the_park(self):
        """No Genau behind that screen, and the script's own driver rests the
        device — so past the buffer the picture is the park, not a stroke that
        is not coming."""
        hud = drive_readout(
            None, script=_script(until_ms=2_000), position_ms=0,
            genau_behind=False)
        gap_start = hud.runs[-1][0]

        assert _colors(hud) == [
            DRIVEN_BY_FUNSCRIPT, DRIVEN_BY_NEUTRAL, DRIVEN_BY_NOTHING]
        assert set(hud.waveform[gap_start:]) == {0.0}


class TestTheRampDownOntoThePark:
    """Genau's turn ends when the script's turn opens — a time the script fixes
    — and the device walks from wherever that leaves it down onto the park.

    It used to end on the stroke's next floor-touch instead, which only the
    live stroke knew and which moved under the picture every frame: the final
    cycle flickered in and out, and vanished outright the moment Genau paused.
    """

    def test_the_blue_runs_to_the_moment_the_script_turn_opens(self):
        script = _script_ahead()               # its turn opens at 3000ms
        hud = _read(script, at=0)

        assert hud.runs[0][1] == 3_000 // STEP_MS

    def test_the_ramp_starts_where_the_stroke_is_and_reaches_the_park(self):
        published = _stroke()
        hud = _read(_script_ahead(), at=0, published=published)
        opens = 3_000 // STEP_MS

        assert hud.waveform[opens] == published.waveform[opens]   # where Genau will be
        descent = hud.waveform[opens:opens + RAMP_STEPS + 1]
        for left, right in zip(descent, descent[1:]):
            assert right < left
        assert hud.waveform[opens + RAMP_STEPS] == 0.0            # the park

    def test_the_ramp_is_the_buffer_s_grey_not_genau_s_blue(self):
        hud = _read(_script_ahead(), at=0)

        assert hud.runs[1][2] == DRIVEN_BY_NEUTRAL

    def test_it_holds_still_as_the_picture_slides(self):
        """Two whole steps on, everything is exactly two columns left — no
        recomputed moment to move under it."""
        script = _script_ahead()

        first = _read(script, at=0, published=_stroke_at(0)).waveform
        later = _read(script, at=2 * STEP_MS,
                      published=_stroke_at(2 * STEP_MS)).waveform

        assert later[:-2] == first[2:]

    def test_the_published_let_go_carries_the_ramp_after_the_flip(self):
        """A paused Genau publishes the stroke it will resume with, not where
        it stopped — so the height it let go at rides the publish, latched at
        the source, and the descent keeps drawing from it."""
        script = _script_ahead()

        after = _read(script, at=3_000, published=_parked_stroke(let_go=0.73))

        assert after.waveform[0] == 0.73             # the descent opens there...
        assert after.waveform[RAMP_STEPS] == 0.0     # ...and lands on the park

    def test_the_dot_walks_down_the_ramp_with_the_device(self):
        script = _script_ahead()
        published = _parked_stroke(let_go=0.8)

        opened = _read(script, at=3_000, published=published)
        midway = _read(script, at=3_000 + HANDOFF_RAMP_MS // 2, published=published)
        landed = _read(script, at=3_000 + HANDOFF_RAMP_MS, published=published)

        assert opened.position == round(0.8 * POSITION_MAX)
        assert landed.position == 0
        assert landed.position < midway.position < opened.position


class TestTheClimbBackOut:
    """The mirror: the script gives the device back a handoff ramp before the
    quiet ends, and the buffer climbs it from the park onto the stroke's floor
    — so the stroke begins where it always did, at the far end of the quiet,
    having walked there instead of lunging at the end."""

    def test_the_buffer_climbs_from_the_park_to_the_stroke(self):
        published = _parked_stroke()
        hud = _read(_script(until_ms=2_000), at=1_000, published=published)
        blue_start = hud.runs[-1][0]

        assert hud.waveform[blue_start - RAMP_STEPS] == 0.0
        rising = hud.waveform[blue_start - RAMP_STEPS:blue_start + 1]
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

    def test_a_stroke_opening_on_the_park_needs_no_climb(self):
        """Full amplitude: the park already IS the stroke's floor.  The sender
        skips its rise there and the blue begins the moment Genau's turn does —
        drawn any other way, the picture waited two seconds the device did not."""
        published = _parked_stroke(
            amplitude=100,
            waveform=tuple(0.5 - 0.5 * np.cos(i / 6) for i in range(TRACE_SAMPLES)))
        script = _script(until_ms=2_000)
        hud = _read(script, at=1_000, published=published)
        blue_start = hud.runs[-1][0]

        # The first sample past the script's turn (its end is inclusive) — by
        # which the stroke, begun at the boundary itself, is one sample in.
        assert 1_000 + blue_start * STEP_MS == 2_000 + 3_000 + STEP_MS
        assert hud.waveform[blue_start] == published.waveform[1]


class TestAFloorOnTheParkEndsOnItsTouchDown:
    """His rule, restated for the third and final time: when the stroke's floor
    rests ON the park (full amplitude), there is NO ramp — the blue swings on
    past the boundary to its next touch-down, the grey runs flat from there,
    and the arbiter really does hold the device's flip for that same touch."""

    def _touching_stroke(self, **over) -> DriveHud:
        # 0.5 + 0.5·sin(i/3): the floor IS the park, touched near samples 14,
        # 33, 52, 71 — well inside the shared wait cap past a 3000ms boundary.
        over.setdefault(
            "waveform",
            tuple(0.5 + 0.5 * np.sin(i / 3) for i in range(TRACE_SAMPLES)))
        return _stroke(amplitude=100, **over)

    def test_no_ramp_and_the_grey_runs_flat(self):
        hud = _read(_script_ahead(), at=0, published=self._touching_stroke(),
                    descent_tops={})
        blue_end = hud.runs[0][1]
        green_start = hud.runs[-1][0]

        assert _colors(hud) == [
            DRIVEN_BY_GENAU, DRIVEN_BY_NEUTRAL, DRIVEN_BY_FUNSCRIPT]
        assert hud.waveform[blue_end] <= 0.03            # ends ON the park...
        flat = hud.waveform[blue_end + 1:green_start - 10]
        assert max(flat) <= 0.03                          # ...and stays flat

    def test_the_blue_swings_past_the_boundary_to_the_touch(self):
        hud = _read(_script_ahead(), at=0, published=self._touching_stroke(),
                    descent_tops={})
        blue_end_ms = hud.runs[0][1] * STEP_MS

        assert blue_end_ms > 3_000                        # past the turn boundary

    def test_the_touch_is_selected_once(self):
        script = _script_ahead()
        tops: dict = {}

        first = _read(script, at=0, published=self._touching_stroke(),
                      descent_tops=tops)
        # A publish a beat newer — the wobble that used to re-pick the moment.
        later = _read(script, at=0, published=self._touching_stroke(
            waveform=tuple(0.5 + 0.5 * np.sin((i + 0.3) / 3)
                           for i in range(TRACE_SAMPLES))), descent_tops=tops)

        assert later.runs[0][1] == first.runs[0][1]

    def test_the_extension_is_the_published_wave_itself(self):
        """The samples past the boundary belong to the stretch ENDING there:
        they must read the live wave's own continuation.  Resolved from the
        sample's own bounds they picked up the SCRIPT turn's and re-anchored
        the wave as a future resumed one — the drawn ending landed a whole
        swing away from the park it claimed to touch."""
        published = self._touching_stroke()
        hud = _read(_script_ahead(), at=0, published=published, descent_tops={})
        blue_end = hud.runs[0][1]

        # The run's end column is the grey's first sample (runs share their
        # boundary), and the final approach eases onto the park so the seam
        # cannot flicker — so the exact-wave comparison stops short of both,
        # and the feathered tail must sit between the wave and the park.
        feather_columns = 300 // STEP_MS
        for column in range(3_000 // STEP_MS, blue_end - feather_columns):
            assert hud.waveform[column] == published.waveform[column]
        for column in range(blue_end - feather_columns, blue_end):
            assert 0.0 <= hud.waveform[column] <= published.waveform[column] + 1e-9

    def test_a_far_boundary_stays_a_live_forecast(self):
        """The published wave is a projection that drifts over ten seconds —
        a touch latched the moment its turn scrolled into view arrived a whole
        swing wrong.  The choice is latched only inside the freeze horizon,
        where the projection is as fresh as the arbiter's own."""
        script = _script_ahead(from_ms=18_000, to_ms=19_000)  # boundary 13000
        tops: dict = {}

        _read(script, at=2_000, published=self._touching_stroke(),
              descent_tops=tops)
        assert tops == {}                       # too far: still a forecast

        _read(script, at=10_040, published=self._touching_stroke(),
              descent_tops=tops)
        assert 13_000 in tops                   # inside the horizon: latched

    def test_a_raised_floor_still_ramps(self):
        hud = _read(_script_ahead(), at=0, descent_tops={})   # amplitude 80
        opens = 3_000 // STEP_MS

        assert hud.runs[1][2] == DRIVEN_BY_NEUTRAL
        descent = hud.waveform[opens:opens + 5]
        for left, right in zip(descent, descent[1:]):
            assert right < left


class TestTheDescentTopIsSelectedOnce:
    """The pre-handoff ramp top is a prediction read off the live blue, and the
    live blue moves a hair with every publish — re-read per frame, the seam
    flickered between "blue ends on the park" and a slightly diagonal ramp.
    Selected once per (turn, controls, publish-state) and held, it cannot."""

    def test_the_held_top_does_not_move_with_the_publish(self):
        script = _script_ahead()
        tops: dict = {}
        opens = 3_000 // STEP_MS

        first = _read(script, at=0, published=_stroke_at(0), descent_tops=tops)
        # The next frame's publish is a beat newer than the playhead — the
        # exact mismatch that used to re-shape the ramp.
        later = _read(script, at=0, published=_stroke_at(20), descent_tops=tops)

        assert later.waveform[opens] == first.waveform[opens]

    def test_an_omnipause_park_re_selects_the_top(self):
        """Genau hands the device over when OmniPause lands and realigns its
        wave to the park; the publish's let_go edge is what re-keys the latch,
        so the ramp is re-read from the wave as it now stands."""
        script = _script_ahead()
        tops: dict = {}
        opens = 3_000 // STEP_MS

        live = _read(script, at=0, published=_stroke(), descent_tops=tops)
        parked = _read(script, at=0, published=_parked_stroke(let_go=0.44),
                       descent_tops=tops)

        assert parked.waveform[opens] != live.waveform[opens]

    def test_the_wave_coming_live_again_re_selects_the_top(self):
        """The other half of the OmniPause round trip: when the climb finishes
        and the publish runs again (let_go cleared), the held prediction from
        the frozen wave is stale, and the fresh live wave re-tops the ramp."""
        script = _script_ahead()
        tops: dict = {}
        opens = 3_000 // STEP_MS

        frozen = _read(script, at=0, published=_parked_stroke(let_go=0.44),
                       descent_tops=tops)
        resumed = _read(script, at=0, published=_stroke_at(0), descent_tops=tops)

        assert resumed.waveform[opens] != frozen.waveform[opens]

    @pytest.mark.parametrize("control, moved_to", [
        ("amplitude", 90), ("center", 60), ("speed", 70),
    ])
    def test_moving_a_control_re_selects_the_top(self, control, moved_to):
        """Every field of the latch's key, one case each.

        The held choice is carried while the controls stand still -- which is
        what the sibling above pins -- so the newer publish below can only reach
        the ramp if moving the control re-keyed the latch.  Dropping any one of
        the three from the key leaves that field's case carrying instead.
        """
        script = _script_ahead()
        opens = 3_000 // STEP_MS
        tops: dict = {}

        first = _read(script, at=0, published=_stroke_at(0), descent_tops=tops)
        moved = _read(script, at=0, published=_stroke_at(20, **{control: moved_to}),
                      descent_tops=tops)

        assert moved.waveform[opens] != first.waveform[opens]


class TestStillPicture:
    """He watched the line boil, twitch and flicker in turn.  Every one of
    those was a value that depended on something other than the playhead."""

    def test_the_shape_slides_along_rather_than_being_redrawn(self):
        script = _script(until_ms=120_000)

        first = _read(script, at=0).waveform
        later = _read(script, at=2 * STEP_MS).waveform

        assert later[:-2] == first[2:]

    def test_the_whole_handoff_slides_rigidly_too(self):
        """Through a funscript's turn Genau's publish is frozen, so between two
        frames the settle, the rest, the climb and the waiting stroke are all
        exactly the same values, two columns to the left."""
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

    def test_the_live_stroke_reads_fixed_times_so_the_painter_slides_it(self):
        """The live blue is read at fixed absolute sample times: as the playhead
        moves within a knot and the publish advances in step with it, the value
        drawn at each column compensates the publish's own motion, so the whole
        line — blue included — slides on the painter's one shift.  Reading it by
        column instead left the blue on a different convention from every other
        run, and the two disagreed by the slide at each seam between them."""
        script = _script_ahead()

        # Column 0's sample time sits a fraction of a knot BEHIND the playhead,
        # where a forward-window publish has nothing; it clamps to now and is
        # drawn off the box's left edge — so the invariant starts at column 1.
        pictures = [
            _read(script, at=at, published=_stroke_at(at)).waveform[1:20]
            for at in (0, 40, 80)
        ]

        for later in pictures[1:]:
            for a, b in zip(pictures[0], later):
                assert abs(a - b) < 0.005


class TestPositionMarker:
    """The dot rides the drawn line, always: Genau's published position only
    inside live blue — where it IS the line, at the device's own finer rate —
    and the line's own value everywhere else, so it can never ride a line that
    is not there."""

    def test_a_script_driving_puts_the_marker_where_the_plan_has_the_device(self):
        script = _script(until_ms=120_000)

        hud = _read(script, at=400)

        assert hud.position == round(
            script.planned_position_at(400) / 100 * POSITION_MAX)

    def test_a_script_holding_the_device_parked_rests_the_marker_on_the_park(self):
        """Through the lead-in the device sits at its park; a marker riding the
        script's interpolated line floated where nothing was."""
        script = _script_ahead(from_ms=40_000, to_ms=41_000)

        hud = _read(script, at=37_000, published=_parked_stroke())

        assert script.is_resting_at(37_000) is False
        assert hud.position == 0

    def test_genau_driving_leaves_the_marker_where_genau_published_it(self):
        """It is Genau's device then, and Genau knows where it put it."""
        published = _stroke(position=1234)

        hud = _read(_script_ahead(), at=0, published=published)

        assert hud.position == 1234

    def test_the_dot_climbs_the_drawn_ramp_out_of_the_park(self):
        script = _script(until_ms=2_000)
        published = _parked_stroke()

        resting = _read(script, at=4_500, published=published)
        midway = _read(script, at=5_000 + HANDOFF_RAMP_MS // 2, published=published)

        assert resting.position == 0
        assert 0 < midway.position < round(0.2 * POSITION_MAX)


class TestTheSeamCannotFlicker:
    """The live blue breathes a hair with every publish; feathered onto the
    latched seam value, the join's neighbourhood converges to a constant — the
    residual indecision he watched at the blue-to-grey point."""

    def test_the_last_blue_column_sits_on_the_latched_top(self):
        tops: dict = {}
        published = _stroke()                        # amplitude 80: the ramp case
        hud = _read(_script_ahead(), at=1_000, published=published,
                    descent_tops=tops)
        seam = hud.runs[0][1]                        # the grey's first column

        top = tops[3_000][1]
        assert abs(hud.waveform[seam - 1] - top) < 0.12
        # A publish a beat older — the wobble that used to flap the join —
        # moves the seam-adjacent column almost nothing.
        aged = _read(_script_ahead(), at=1_000, published=_stroke_at(20),
                     descent_tops=tops)
        assert abs(aged.waveform[seam - 1] - hud.waveform[seam - 1]) < 0.02


class TestForecastsDieWithTheirWave:
    """A held choice is only as good as the wave it was cut from.  The rewind
    class: after any realignment, the old wave's touch cuts the new wave
    anywhere — so a re-key that is not the flip itself re-chooses, a parked
    publish never seeds a pre-turn latch, and no blue extension is drawn off a
    wave nobody is stroking."""

    def _touching(self, phase: float = 0.0, **over) -> DriveHud:
        over.setdefault(
            "waveform",
            tuple(0.5 + 0.5 * np.sin((i + phase) / 3) for i in range(TRACE_SAMPLES)))
        return _stroke(amplitude=100, **over)

    def test_a_resume_re_chooses_the_touch_for_the_new_wave(self):
        """let_go set (a handoff, an OmniPause) then cleared (the wave running
        again) re-keys twice; the second re-key must re-scan — carried through,
        the old alignment's touch cut the realigned wave mid-swing."""
        script = _script_ahead()
        tops: dict = {}

        first = _read(script, at=0, published=self._touching(), descent_tops=tops)
        _read(script, at=0, published=self._touching(let_go=0.0), descent_tops=tops)
        moved = _read(script, at=0, published=self._touching(phase=9.4),
                      descent_tops=tops)

        assert first.runs[0][1] != moved.runs[0][1]   # the new wave's own touch

    def test_a_parked_publish_never_seeds_a_pre_turn_latch(self):
        """Right after a rewind the publish is still the frozen pre-rewind wave
        for a beat; a forecast latched from it froze the stale touch."""
        script = _script_ahead()
        tops: dict = {}

        _read(script, at=0, published=self._touching(let_go=0.0), descent_tops=tops)

        assert tops == {}

    def test_no_extension_is_drawn_off_a_parked_wave(self):
        """A rewind landing just past a boundary finds the script holding the
        device (let_go published): the drawn line is the buffer and the plan,
        never a blue stroke nobody is making."""
        script = _script_ahead()
        tops: dict = {}
        _read(script, at=2_800, published=self._touching(), descent_tops=tops)

        landed = _read(script, at=3_120, published=self._touching(let_go=0.0),
                       descent_tops=tops)

        assert DRIVEN_BY_GENAU not in _colors(landed)


class TestThePillFollowsTheLine:
    """The console's OSR2 pill reads ``driven`` off the returned readout — set
    here from the same function that drew the line under the dot — so the pill
    flips exactly when the line changes hands, and says Buffer through the
    grey.  Keyed on the round-tripped console state it flipped at the
    arbiter's decision, seconds before the dot finished riding the blue."""

    def test_genau_while_the_dot_rides_the_extension(self):
        published = _stroke(
            amplitude=100,
            waveform=tuple(0.5 + 0.5 * np.sin(i / 3) for i in range(TRACE_SAMPLES)))
        # 3320ms is past the boundary (3000) but before the touch-down.
        hud = _read(_script_ahead(), at=3_320, published=published,
                    descent_tops={})

        assert hud.driven == DRIVEN_BY_GENAU

    def test_buffer_through_the_grey(self):
        hud = _read(_script_ahead(), at=4_500, published=_parked_stroke())

        assert hud.driven == DRIVEN_BY_NEUTRAL

    def test_funscript_through_the_cluster(self):
        hud = _read(_script(until_ms=120_000), at=1_000)

        assert hud.driven == DRIVEN_BY_FUNSCRIPT


class TestThePublishedTouch:
    """Nau tells the arbiter which touch-down it drew the blue ending on, so
    the device is set down exactly there — one chooser.  When each side chose
    from its own read of the wave, the arbiter could take an earlier touch,
    and the leftover drawn blue vanished the moment the dot reached it."""

    def test_the_latched_touch_is_what_gets_published(self):
        from nau.status import next_handoff_touch
        script = _script_ahead()
        tops: dict = {}
        published = _stroke(
            amplitude=100,
            waveform=tuple(0.5 + 0.5 * np.sin(i / 3) for i in range(TRACE_SAMPLES)))
        hud = _read(script, at=1_000, published=published, descent_tops=tops)
        blue_end_ms = 1_000 + hud.runs[0][1] * STEP_MS

        # Approaching the boundary (resting) and inside the extension (not
        # resting) both name the same turn's touch.
        assert next_handoff_touch(script, 1_000, tops) == tops[3_000][2]
        assert next_handoff_touch(script, 3_200, tops) == tops[3_000][2]
        assert abs(next_handoff_touch(script, 1_000, tops) - blue_end_ms) <= STEP_MS

    def test_a_ramp_boundary_publishes_no_touch(self):
        from nau.status import next_handoff_touch
        script = _script_ahead()
        tops: dict = {}
        _read(script, at=1_000, descent_tops=tops)          # amplitude 80: ramp

        assert next_handoff_touch(script, 1_000, tops) is None

    def test_nothing_latched_publishes_no_touch(self):
        from nau.status import next_handoff_touch

        assert next_handoff_touch(_script_ahead(), 1_000, {}) is None
        assert next_handoff_touch(None, 1_000, {}) is None


class TestNothingToFoldIn:
    def test_an_unscripted_video_leaves_the_readout_alone(self):
        published = _stroke()

        assert drive_readout(published, script=None, position_ms=0,
                             genau_behind=True) == published

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
