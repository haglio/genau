from __future__ import annotations

import pytest

from genau_vr.playback import (
    DirectControlState,
    PlaybackEngine,
    WaveformShape,
    bpm_for_speed,
    cycle_shape,
    display_index_for_phase,
    display_phase_for_position,
    format_tcode_command,
    phase_to_position,
    update_engine,
)
from genau_vr.runtime_commands import apply_runtime_command


class TestCycleShapeReverse:
    def test_step_minus_one_goes_backward(self):
        state = DirectControlState(playing=True, shape=WaveformShape.TRIANGLE)
        cycle_shape(state, -1)
        assert state.shape is WaveformShape.SINE

    def test_backward_wraps_from_first_to_last(self):
        state = DirectControlState(playing=True, shape=WaveformShape.SINE)
        cycle_shape(state, -1)
        assert state.shape is WaveformShape.SAWTOOTH

    def test_cycle_shape_prev_command_reverses_shape(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        ds = DirectControlState(playing=True)
        assert ds.shape is WaveformShape.SINE

        handled = apply_runtime_command(
            "CYCLE_SHAPE_PREV",
            engine=engine,
            rh_paused={"value": False},
            step_clip=lambda _step: None,
            direct_state=ds,
        )

        assert handled is True
        assert ds.shape is WaveformShape.SAWTOOTH


class TestBpmForSpeed:
    def test_min_speed_gives_min_bpm(self):
        assert bpm_for_speed(5) == pytest.approx(5.0)

    def test_max_speed_gives_max_bpm(self):
        assert bpm_for_speed(100) == pytest.approx(200.0)

    def test_speed_50_is_between(self):
        bpm = bpm_for_speed(50)
        assert 5.0 < bpm < 200.0


class TestDirectControlState:
    def test_default_state(self):
        state = DirectControlState(playing=True, speed=50)
        assert state.playing is True
        assert state.speed == 50
        assert state.bpm == pytest.approx(bpm_for_speed(50))
        assert state.shape is WaveformShape.SINE

    def test_amplitude_default(self):
        state = DirectControlState()
        assert state.amplitude == 100
        assert state.center == 50


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


class TestUpdateEngine:
    def test_phase_advances(self):
        engine = PlaybackEngine(last_tick=0.0)
        update_engine(
            engine,
            now=0.5,
            auto_active=True,
            raw_bpm=60.0,
            sync_pulse_id=0,
            beats_per_loop=1.0,
            bpm_smoothing=1.0,
            sync_strength=0.0,
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
            sync_pulse_id=0,
            beats_per_loop=1.0,
            bpm_smoothing=1.0,
            sync_strength=0.0,
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


class TestDisplayPhaseForPosition:
    def test_sine_phase_zero_returns_zero(self):
        assert display_phase_for_position(0.0, WaveformShape.SINE) == pytest.approx(0.0)

    def test_sine_phase_half_returns_half(self):
        assert display_phase_for_position(0.5, WaveformShape.SINE) == pytest.approx(0.5)
