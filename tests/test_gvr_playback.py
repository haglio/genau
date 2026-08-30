from __future__ import annotations

import dataclasses
import pytest

from genau_vr.playback import (
    DirectControlState,
    PlaybackEngine,
    WaveformShape,
    bpm_for_speed,
    cycle_shape,
    display_index_for_phase,
    _waveform_raw,
    display_phase_for_position,
    format_tcode_command,
    phase_to_position,
    set_amplitude,
    set_speed,
    update_engine,
)


class TestCycleShape:
    def test_it_walks_the_shapes_in_order(self):
        state = DirectControlState(playing=True, shape=WaveformShape.TRIANGLE)

        cycle_shape(state)

        assert state.shape is WaveformShape.ROUNDED_SQUARE

    def test_it_wraps_from_the_last_shape_to_the_first(self):
        state = DirectControlState(playing=True, shape=WaveformShape.SAWTOOTH)

        cycle_shape(state)

        assert state.shape is WaveformShape.SINE

    def test_it_goes_one_way(self):
        """GenauVR cycles forward only -- CYCLE_SHAPE_PREV had no phrase and
        is gone, so a step argument would be a direction nothing can ask for."""
        import pytest

        with pytest.raises(TypeError):
            cycle_shape(DirectControlState(), -1)


class TestBpmForSpeed:
    """The curve is exponential, and "between the ends" is true of a straight
    line as well -- which is why swapping the geometric mapping for a linear one
    used to leave every case here green."""

    def test_min_speed_gives_min_bpm(self):
        assert bpm_for_speed(5) == pytest.approx(5.0)

    def test_max_speed_gives_max_bpm(self):
        assert bpm_for_speed(100) == pytest.approx(200.0)

    def test_the_middle_of_the_range_is_the_geometric_mean_of_the_ends(self):
        """Half the speed range is half the *ratio*, not half the difference:
        a straight line would put this at 102.5."""
        assert bpm_for_speed(52.5) == pytest.approx(31.6228, abs=0.001)

    def test_speed_50_is_the_number_the_player_opens_on(self):
        assert bpm_for_speed(50) == pytest.approx(28.6973, abs=0.001)


class TestDirectControlState:
    def test_default_state(self):
        state = DirectControlState(playing=True, speed=50)
        assert state.playing is True
        assert state.speed == 50
        # A number, not a call to the function that computed it: comparing it
        # to bpm_for_speed(50) compares the value to itself.
        assert state.bpm == pytest.approx(28.6973, abs=0.001)
        assert state.shape is WaveformShape.SINE

    def test_amplitude_default(self):
        state = DirectControlState()
        assert state.amplitude == 100
        assert state.center == 50


class TestTheCentreTheSwingIsBuiltAround:
    """The centre asked for and the centre reachable are two things: a swing
    cannot be centred somewhere its own travel would take it off either end."""

    def test_a_full_swing_can_only_be_centred_in_the_middle(self):
        state = DirectControlState(amplitude=100, intended_center=20)

        assert state.center == 50
        assert state.intended_center == 20, "what was asked for survives the clamp"

    @pytest.mark.parametrize("asked_for, reachable", [(10, 20), (50, 50), (95, 80)])
    def test_a_narrower_swing_can_travel(self, asked_for, reachable):
        """Amplitude 40 leaves half of it, 20, clear at each end."""
        state = DirectControlState(amplitude=40, intended_center=asked_for)

        assert state.center == reachable

    def test_widening_the_swing_pulls_the_centre_back_in(self):
        """The clamp is re-run on every change, not only on the centre's own:
        without that, widening around a raised centre swings off the top."""
        state = DirectControlState(amplitude=40, intended_center=80)

        set_amplitude(state, 100)

        assert state.center == 50
        assert state.intended_center == 80, "the swing comes back when it narrows"


class TestTheSpeedRange:
    @pytest.mark.parametrize("asked_for, held_at", [(-20, 5), (0, 5), (5, 5),
                                                    (100, 100), (400, 100)])
    def test_a_speed_outside_the_range_saturates(self, asked_for, held_at):
        state = DirectControlState()

        set_speed(state, asked_for)

        assert state.speed == held_at

    def test_the_pace_follows_the_speed_that_was_actually_taken(self):
        """Not the one that was asked for -- a clamped speed with an unclamped
        bpm would drive the device faster than the control says."""
        state = DirectControlState()

        set_speed(state, 400)

        assert state.bpm == pytest.approx(200.0)


class TestPhaseToPosition:
    def test_sine_phase_zero_gives_zero_position(self):
        pos = phase_to_position(0.0)
        assert pos == 0

    def test_sine_phase_half_gives_max_position(self):
        pos = phase_to_position(0.5)
        assert pos == 9999

    def test_sine_phase_one_returns_to_zero(self):
        pos = phase_to_position(1.0)
        assert pos == pytest.approx(0, abs=1)

    def test_a_narrowed_swing_runs_the_middle_of_the_range(self):
        assert phase_to_position(0.0, amplitude=50) == 2500
        assert phase_to_position(0.5, amplitude=50) == 7499

    def test_a_raised_centre_lifts_both_ends(self):
        assert phase_to_position(0.0, amplitude=40, center=70) == 4999
        assert phase_to_position(0.5, amplitude=40, center=70) == 8999


class TestEachWaveformShape:
    """Every shape at the phases that tell it apart from its neighbours.

    All four rise from the floor at phase 0 and all four reach the top at their
    own peak, so the ends alone say nothing: the quarter and three-quarter
    points are where a shape replaced by a constant, or by another shape, shows.
    """

    SHAPES = {
        WaveformShape.SINE: [0, 2061, 4999, 6544, 9999, 7938, 5000],
        WaveformShape.TRIANGLE: [0, 3000, 5000, 5999, 9999, 6999, 5000],
        WaveformShape.ROUNDED_SQUARE: [0, 262, 4999, 8663, 9999, 9737, 5000],
        # The only one that is not symmetric about its peak: it rises over the
        # first three tenths and falls over the other seven.
        WaveformShape.SAWTOOTH: [0, 5000, 8332, 9999, 7142, 4999, 3571],
    }
    PHASES = (0.0, 0.15, 0.25, 0.3, 0.5, 0.65, 0.75)

    @pytest.mark.parametrize("shape, positions", sorted(SHAPES.items(), key=lambda kv: kv[0].value),
                             ids=[s.name for s in sorted(SHAPES, key=lambda s: s.value)])
    def test_the_swing_travels_the_way_this_shape_says(self, shape, positions):
        travelled = [phase_to_position(phase, shape=shape) for phase in self.PHASES]

        assert travelled == positions

    def test_no_two_shapes_travel_the_same_way(self):
        """A shape wired to its neighbour's branch would otherwise be a rename
        away from passing every row above."""
        assert len({tuple(row) for row in self.SHAPES.values()}) == len(self.SHAPES)


class TestUpdateEngine:
    def test_the_engine_holds_no_sync_state(self):
        """GenauVR has no bus to be pulsed from.

        Genau's engine follows a SYNC verb its UDP listener counts; this copy
        was taken from that one and kept the machinery, with the single call
        site passing sync_pulse_id=0 and sync_strength=0.0 forever -- so the
        phase correction could never fire and no test reached it either.
        """
        assert {f.name for f in dataclasses.fields(PlaybackEngine)} == {
            "phase", "estimated_bpm", "target_bpm", "last_tick",
        }

    def test_phase_advances(self):
        engine = PlaybackEngine(last_tick=0.0)
        update_engine(
            engine,
            now=0.5,
            auto_active=True,
            raw_bpm=60.0,
            beats_per_loop=1.0,
            bpm_smoothing=1.0,
            paused=False,
        )
        # dt clamped to 0.1, loop=1s at 60bpm → phase=0.1 after first tick
        # But now=0.5 and last_tick=0.0, dt=0.5 clamped to 0.1
        assert engine.phase == pytest.approx(0.1, abs=0.001)

    def test_paused_does_not_advance(self):
        engine = PlaybackEngine(last_tick=0.0)
        update_engine(
            engine,
            now=0.5,
            auto_active=True,
            raw_bpm=60.0,
            beats_per_loop=1.0,
            bpm_smoothing=1.0,
            paused=True,
        )
        assert engine.phase == 0.0


class TestFormatTcodeCommand:
    def test_basic_format(self):
        cmd = format_tcode_command("L0", 5000, 33)
        assert cmd == "L05000I33"

    def test_clamps_position(self):
        cmd = format_tcode_command("L0", 99999, 33)
        assert cmd == "L09999I33"


class TestDisplayIndexForPhase:
    def test_phase_zero_gives_first_frame(self):
        idx = display_index_for_phase(phase=0.0, frame_count=10, auto_active=True, current_frame_index=None)
        assert idx == 0

    def test_phase_near_one_gives_last_frame(self):
        idx = display_index_for_phase(phase=0.99, frame_count=10, auto_active=True, current_frame_index=None)
        assert idx == 9

    def test_paused_holds_current(self):
        idx = display_index_for_phase(phase=0.5, frame_count=10, auto_active=False, current_frame_index=3)
        assert idx == 3

    def test_a_phase_that_reached_the_end_still_names_a_frame_that_exists(self):
        """phase 1.0 multiplies out to the frame past the last one, and a clip
        indexed there raises rather than drawing anything."""
        idx = display_index_for_phase(phase=1.0, frame_count=10, auto_active=True,
                                      current_frame_index=None)

        assert idx == 9

    def test_paused_before_the_first_frame_has_been_chosen_still_advances(self):
        idx = display_index_for_phase(phase=0.5, frame_count=10, auto_active=False,
                                      current_frame_index=None)

        assert idx == 5


class TestDisplayPhaseForPosition:
    def test_sine_phase_zero_returns_zero(self):
        assert display_phase_for_position(0.0, WaveformShape.SINE) == pytest.approx(0.0)

    def test_sine_phase_half_returns_half(self):
        assert display_phase_for_position(0.5, WaveformShape.SINE) == pytest.approx(0.5)


def test_a_shape_the_waveform_does_not_know_is_refused():
    """The four branches cover the enum; there is no fifth answer to give.

    The chain used to end in a verbatim copy of the SINE branch, unreachable
    and reading as a meaningful default -- so a fifth shape added later would
    have come out a sine rather than a failure. _PEAK_PHASE, ten lines below,
    raises KeyError on a shape it does not know; the two now agree.
    """
    with pytest.raises(ValueError):
        _waveform_raw(0.25, "not-a-shape")
