from __future__ import annotations

import pytest

from genau.direct_control import (
    DirectControlState,
    WaveformShape,
    adjust_amplitude,
    adjust_center,
    adjust_speed,
    bpm_for_speed,
    cycle_shape,
    display_phase_for_position,
    pause_playing,
    phase_to_position,
    sample_waveform,
    set_amplitude,
    set_center,
    set_speed,
    space_action,
    toggle_playing,
)


class TestBpmForSpeed:
    def test_min_speed_returns_minimum_bpm(self):
        assert bpm_for_speed(5) == pytest.approx(5.0)

    def test_speed_100_returns_maximum_bpm(self):
        assert bpm_for_speed(100) == pytest.approx(200.0)

    def test_monotonically_increasing(self):
        bpms = [bpm_for_speed(i) for i in range(5, 101, 5)]
        for i in range(len(bpms) - 1):
            assert bpms[i] < bpms[i + 1]

    def test_exponential_curve_gives_finer_control_at_low_end(self):
        low_step = bpm_for_speed(10) - bpm_for_speed(5)
        high_step = bpm_for_speed(100) - bpm_for_speed(95)
        assert low_step < high_step


class TestTogglePlaying:
    def test_false_to_true(self):
        state = DirectControlState()
        toggle_playing(state)
        assert state.playing is True

    def test_true_to_false(self):
        state = DirectControlState(playing=True)
        toggle_playing(state)
        assert state.playing is False


class TestPausePlaying:
    def test_pauses_when_playing(self):
        state = DirectControlState(playing=True)
        pause_playing(state)
        assert state.playing is False

    def test_noop_when_already_paused(self):
        state = DirectControlState(playing=False)
        pause_playing(state)
        assert state.playing is False


class TestSpaceAction:
    def test_solo_toggles_on(self):
        state = DirectControlState(playing=False)
        space_action(state, pause_only=False)
        assert state.playing is True

    def test_solo_toggles_off(self):
        state = DirectControlState(playing=True)
        space_action(state, pause_only=False)
        assert state.playing is False

    def test_fun_time_only_pauses(self):
        state = DirectControlState(playing=True)
        space_action(state, pause_only=True)
        assert state.playing is False

    def test_fun_time_does_not_resume(self):
        state = DirectControlState(playing=False)
        space_action(state, pause_only=True)
        assert state.playing is False


class TestSetSpeed:
    def test_sets_speed_and_bpm(self):
        state = DirectControlState()
        set_speed(state, 30)
        assert state.speed == 30
        assert state.bpm == pytest.approx(bpm_for_speed(30))

    def test_clamps_below_minimum_to_5(self):
        state = DirectControlState()
        set_speed(state, 0)
        assert state.speed == 5

    def test_clamps_above_100(self):
        state = DirectControlState()
        set_speed(state, 105)
        assert state.speed == 100


class TestTriangleWaveform:
    def test_phase_0_returns_base(self):
        assert phase_to_position(0.0, shape=WaveformShape.TRIANGLE) == 0

    def test_phase_quarter_returns_midpoint(self):
        assert phase_to_position(0.25, shape=WaveformShape.TRIANGLE) == pytest.approx(5000, abs=1)

    def test_phase_half_returns_tip(self):
        assert phase_to_position(0.5, shape=WaveformShape.TRIANGLE) == 9999

    def test_phase_three_quarter_returns_midpoint(self):
        assert phase_to_position(0.75, shape=WaveformShape.TRIANGLE) == pytest.approx(5000, abs=1)

    def test_phase_1_returns_base(self):
        assert phase_to_position(1.0, shape=WaveformShape.TRIANGLE) == pytest.approx(0, abs=1)


class TestRoundedSquareWaveform:
    def test_phase_0_returns_base(self):
        assert phase_to_position(0.0, shape=WaveformShape.ROUNDED_SQUARE) == 0

    def test_phase_half_returns_tip(self):
        assert phase_to_position(0.5, shape=WaveformShape.ROUNDED_SQUARE) == 9999

    def test_phase_1_returns_base(self):
        assert phase_to_position(1.0, shape=WaveformShape.ROUNDED_SQUARE) == pytest.approx(0, abs=1)

    def test_flatter_near_tip_than_sine(self):
        # At phase 0.4 (near tip), rounded square should be closer to 9999 than sine
        sq = phase_to_position(0.4, shape=WaveformShape.ROUNDED_SQUARE)
        sine = phase_to_position(0.4, shape=WaveformShape.SINE)
        assert sq > sine

    def test_flatter_near_base_than_sine(self):
        # At phase 0.1 (near base), rounded square should be closer to 0 than sine
        sq = phase_to_position(0.1, shape=WaveformShape.ROUNDED_SQUARE)
        sine = phase_to_position(0.1, shape=WaveformShape.SINE)
        assert sq < sine


class TestSawtoothWaveform:
    def test_phase_0_returns_base(self):
        assert phase_to_position(0.0, shape=WaveformShape.SAWTOOTH) == 0

    def test_phase_half_is_falling(self):
        # At 0.5, sawtooth is in the slow-fall region (past the 0.3 peak)
        # raw = 1 - (0.5 - 0.3) / 0.7 ≈ 0.714
        pos = phase_to_position(0.5, shape=WaveformShape.SAWTOOTH)
        assert 6000 < pos < 8000

    def test_peak_at_rise_fraction(self):
        # Peak should be at phase 0.3 (the rise fraction)
        assert phase_to_position(0.3, shape=WaveformShape.SAWTOOTH) == 9999

    def test_phase_1_returns_base(self):
        assert phase_to_position(1.0, shape=WaveformShape.SAWTOOTH) == pytest.approx(0, abs=1)

    def test_asymmetric_rise_is_faster(self):
        # At phase 0.15 (half of rise), should be ~50% up
        pos = phase_to_position(0.15, shape=WaveformShape.SAWTOOTH)
        assert 4000 < pos < 6000


class TestWaveformContinuousPhase:
    """All shapes must work with continuous phase > 1.0 (accumulated stroke_phase)."""

    @pytest.mark.parametrize("shape", list(WaveformShape))
    def test_phase_1_5_matches_phase_0_5(self, shape):
        # phase 1.5 should give the same position as phase 0.5 (one full cycle later)
        assert phase_to_position(1.5, shape=shape) == pytest.approx(
            phase_to_position(0.5, shape=shape), abs=1
        )

    @pytest.mark.parametrize("shape", list(WaveformShape))
    def test_phase_2_matches_phase_0(self, shape):
        assert phase_to_position(2.0, shape=shape) == pytest.approx(
            phase_to_position(0.0, shape=shape), abs=1
        )

    @pytest.mark.parametrize("shape", list(WaveformShape))
    def test_result_always_in_range(self, shape):
        for p in [0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0, 1.5, 2.0]:
            pos = phase_to_position(p, shape=shape)
            assert 0 <= pos <= 9999


class TestAmplitudeAndCenter:
    def test_amplitude_50_halves_range(self):
        # At amplitude 50%, center 50%: range is 2500-7499
        tip = phase_to_position(0.5, amplitude=50)
        base = phase_to_position(0.0, amplitude=50)
        assert tip == pytest.approx(7500, abs=1)
        assert base == pytest.approx(2500, abs=1)

    def test_amplitude_100_full_range(self):
        assert phase_to_position(0.5, amplitude=100) == 9999
        assert phase_to_position(0.0, amplitude=100) == 0

    def test_amplitude_0_stays_at_center(self):
        assert phase_to_position(0.0, amplitude=0) == pytest.approx(5000, abs=1)
        assert phase_to_position(0.5, amplitude=0) == pytest.approx(5000, abs=1)

    def test_center_75_shifts_toward_tip(self):
        # amplitude=50, center=75: center at 7499, half_range=2500
        # low=4999, high=9999
        base = phase_to_position(0.0, amplitude=50, center=75)
        tip = phase_to_position(0.5, amplitude=50, center=75)
        assert base == pytest.approx(5000, abs=1)
        assert tip == 9999

    def test_center_25_shifts_toward_base(self):
        base = phase_to_position(0.0, amplitude=50, center=25)
        tip = phase_to_position(0.5, amplitude=50, center=25)
        assert base == 0
        assert tip == pytest.approx(5000, abs=1)

    def test_center_clamping_at_high_amplitude(self):
        # amplitude=100, center=75: center at 7499, half_range=5000
        # low=max(0, 2499)=2499, high=min(9999, 12499)=9999
        base = phase_to_position(0.0, amplitude=100, center=75)
        tip = phase_to_position(0.5, amplitude=100, center=75)
        assert base == pytest.approx(2500, abs=1)
        assert tip == 9999


class TestPhaseToPosition:
    def test_phase_0_returns_base(self):
        assert phase_to_position(0.0) == 0

    def test_phase_quarter_returns_midpoint(self):
        assert phase_to_position(0.25) == pytest.approx(5000, abs=1)

    def test_phase_half_returns_tip(self):
        assert phase_to_position(0.5) == 9999

    def test_phase_three_quarter_returns_midpoint(self):
        assert phase_to_position(0.75) == pytest.approx(5000, abs=1)

    def test_phase_1_returns_base(self):
        assert phase_to_position(1.0) == pytest.approx(0, abs=1)

    def test_continuous_phase_1_5_returns_tip(self):
        assert phase_to_position(1.5) == 9999

    def test_continuous_phase_2_returns_base(self):
        assert phase_to_position(2.0) == pytest.approx(0, abs=1)

    def test_result_always_in_range(self):
        for p in [0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 0.999, 1.5, 2.0, 3.0]:
            pos = phase_to_position(p)
            assert 0 <= pos <= 9999


class TestDirectControlStateNewFields:
    def test_default_amplitude(self):
        state = DirectControlState()
        assert state.amplitude == 100

    def test_default_center(self):
        state = DirectControlState()
        assert state.center == 50

    def test_default_intended_center(self):
        state = DirectControlState()
        assert state.intended_center == 50

    def test_default_shape(self):
        state = DirectControlState()
        assert state.shape is WaveformShape.SINE

class TestSetAmplitude:
    def test_sets_amplitude_directly(self):
        state = DirectControlState(amplitude=30)

        set_amplitude(state, 75)

        assert state.amplitude == 75

    def test_clamps_above_100(self):
        state = DirectControlState(amplitude=50)

        set_amplitude(state, 120)

        assert state.amplitude == 100

    def test_clamps_below_0(self):
        state = DirectControlState(amplitude=50)

        set_amplitude(state, -10)

        assert state.amplitude == 0

    def test_recomputes_center(self):
        state = DirectControlState(amplitude=20, intended_center=90)
        assert state.center == 90  # within range for amp=20

        set_amplitude(state, 100)

        assert state.center == 50  # forced to center for full amplitude


class TestAdjustAmplitude:
    def test_increase(self):
        state = DirectControlState(amplitude=70)
        adjust_amplitude(state, 10)
        assert state.amplitude == 80

    def test_decrease(self):
        state = DirectControlState(amplitude=70)
        adjust_amplitude(state, -10)
        assert state.amplitude == 60

    def test_clamps_at_100(self):
        state = DirectControlState(amplitude=100)
        adjust_amplitude(state, 10)
        assert state.amplitude == 100

    def test_clamps_at_0(self):
        state = DirectControlState(amplitude=0)
        adjust_amplitude(state, -10)
        assert state.amplitude == 0

    def test_increasing_amplitude_pushes_center_toward_50(self):
        state = DirectControlState(amplitude=40, intended_center=80)
        # range [20, 80], center=80 is valid
        adjust_amplitude(state, 10)
        # amplitude=50, range [25, 75], intended=80 is outside → center clamped to 75
        assert state.amplitude == 50
        assert state.center == 75
        assert state.intended_center == 80  # unchanged

    def test_repeated_amplitude_increase_forces_center_to_50(self):
        state = DirectControlState(amplitude=0, intended_center=80)
        for _ in range(10):
            adjust_amplitude(state, 10)
        assert state.amplitude == 100
        assert state.center == 50

    def test_decreasing_amplitude_restores_intended_center(self):
        state = DirectControlState(amplitude=40, intended_center=80)
        # Increase then decrease amplitude
        adjust_amplitude(state, 10)  # amp=50, center clamped to 75
        adjust_amplitude(state, 10)  # amp=60, center clamped to 70
        adjust_amplitude(state, -10)  # amp=50, center restores to 75
        adjust_amplitude(state, -10)  # amp=40, center restores to 80
        assert state.center == 80
        assert state.intended_center == 80


class TestSetCenter:
    def test_sets_intended_center(self):
        state = DirectControlState(amplitude=40, intended_center=50)

        set_center(state, 80)

        assert state.intended_center == 80

    def test_clamps_to_0_100(self):
        state = DirectControlState(amplitude=40)

        set_center(state, 120)

        assert state.intended_center == 100

    def test_recomputes_effective_center(self):
        state = DirectControlState(amplitude=100, intended_center=50)

        set_center(state, 90)

        # With amplitude=100, effective center is clamped to 50
        assert state.intended_center == 90
        assert state.center == 50


class TestAdjustCenter:
    def test_increase(self):
        state = DirectControlState(amplitude=60, intended_center=50)
        adjust_center(state, 10)
        assert state.center == 60
        assert state.intended_center == 60

    def test_decrease(self):
        state = DirectControlState(amplitude=60, intended_center=50)
        adjust_center(state, -10)
        assert state.center == 40
        assert state.intended_center == 40

    def test_half_step_when_5_from_edge(self):
        # amplitude=80, range [40, 60]. intended=55, try +10 → would be 65 > 60
        # 55 is 5 from edge (60), accept half → intended=60
        state = DirectControlState(amplitude=80, intended_center=55)
        adjust_center(state, 10)
        assert state.intended_center == 60
        assert state.center == 60

    def test_ignored_when_at_edge(self):
        # amplitude=80, range [40, 60]. intended=60, try +10 → at edge, ignore
        state = DirectControlState(amplitude=80, intended_center=60)
        adjust_center(state, 10)
        assert state.intended_center == 60
        assert state.center == 60

    def test_center_never_affects_amplitude(self):
        state = DirectControlState(amplitude=80, intended_center=50)
        adjust_center(state, 10)
        assert state.amplitude == 80


class TestCycleShape:
    def test_cycles_from_sine_to_triangle(self):
        state = DirectControlState(shape=WaveformShape.SINE)
        cycle_shape(state)
        assert state.shape is WaveformShape.TRIANGLE

    def test_wraps_from_last_to_first(self):
        state = DirectControlState(shape=WaveformShape.SAWTOOTH)
        cycle_shape(state)
        assert state.shape is WaveformShape.SINE


class TestSampleWaveform:
    def test_returns_correct_number_of_points(self):
        points = sample_waveform(WaveformShape.SINE, amplitude=100, center=50, n_points=60)
        assert len(points) == 60

    def test_all_points_in_0_1_range(self):
        for shape in WaveformShape:
            points = sample_waveform(shape, amplitude=100, center=50, n_points=30)
            for p in points:
                assert 0.0 <= p <= 1.0

    def test_sine_first_point_near_zero(self):
        points = sample_waveform(WaveformShape.SINE, amplitude=100, center=50, n_points=60)
        assert points[0] == pytest.approx(0.0, abs=0.01)

    def test_amplitude_50_scales_range(self):
        points = sample_waveform(WaveformShape.SINE, amplitude=50, center=50, n_points=60)
        # With amplitude=50, center=50: range is 2500-7500, normalized to ~0.25-0.75
        assert min(points) >= 0.24
        assert max(points) <= 0.76


class TestDisplayPhaseForPosition:
    def test_sine_at_base_returns_0(self):
        # phase=0, sine raw=0, going up → display_phase=0
        dp = display_phase_for_position(phase=0.0, shape=WaveformShape.SINE)
        assert dp == pytest.approx(0.0, abs=0.01)

    def test_sine_at_tip_returns_0_5(self):
        dp = display_phase_for_position(phase=0.5, shape=WaveformShape.SINE)
        assert dp == pytest.approx(0.5, abs=0.01)

    def test_triangle_matches_linear_phase(self):
        # Triangle is linear, so display_phase should equal engine phase
        for p in [0.0, 0.1, 0.25, 0.5, 0.75, 0.9]:
            dp = display_phase_for_position(phase=p, shape=WaveformShape.TRIANGLE)
            assert dp == pytest.approx(p, abs=0.02)

    def test_sine_phase_0_1_gives_earlier_display_phase(self):
        # Sine at 0.1: raw≈0.095. Going up → display_phase = raw*0.5 ≈ 0.048
        # This is earlier than 0.1, matching the slower start of sine
        dp = display_phase_for_position(phase=0.1, shape=WaveformShape.SINE)
        assert dp < 0.1

    def test_sawtooth_peak_at_0_3_returns_0_5(self):
        # Sawtooth peaks at frac=0.3 (raw=1), display_phase should be 0.5 (tip)
        dp = display_phase_for_position(phase=0.3, shape=WaveformShape.SAWTOOTH)
        assert dp == pytest.approx(0.5, abs=0.01)


class TestAdjustSpeed:
    def test_increase(self):
        state = DirectControlState(speed=50)
        adjust_speed(state, 5)
        assert state.speed == 55
        assert state.bpm == pytest.approx(bpm_for_speed(55))

    def test_decrease(self):
        state = DirectControlState(speed=50)
        adjust_speed(state, -5)
        assert state.speed == 45

    def test_clamps_at_max(self):
        state = DirectControlState(speed=100)
        adjust_speed(state, 5)
        assert state.speed == 100

    def test_clamps_at_min(self):
        state = DirectControlState(speed=5)
        adjust_speed(state, -5)
        assert state.speed == 5
