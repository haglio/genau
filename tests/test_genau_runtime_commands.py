"""Tests for genau.runtime_commands."""
from __future__ import annotations

import threading

import pytest

from genau.runtime_commands import (
    LEGACY_QUARTER_CYCLE_OFFSET_COMMAND,
    QUARTER_CYCLE_OFFSET_COMMAND,
    apply_runtime_command,
)
from genau.engine import PlaybackEngine
from genau.direct_control import DirectControlState, WaveformShape
from genau.cruise_control import CruiseControlState


class TestApplyRuntimeCommand:
    def test_prev_steps_backward(self):
        steps: list[int] = []
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}

        handled = apply_runtime_command(
            "PREV",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=steps.append,
        )

        assert handled is True
        assert steps == [-1]

    def test_next_steps_forward(self):
        steps: list[int] = []
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}

        handled = apply_runtime_command(
            "NEXT",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=steps.append,
        )

        assert handled is True
        assert steps == [1]

    def test_offset_quarter_cycle_advances_phase(self):
        engine = PlaybackEngine(phase=0.1, last_tick=0.0)
        rh_paused = {"value": False}

        handled = apply_runtime_command(
            QUARTER_CYCLE_OFFSET_COMMAND,
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _step: None,
        )

        assert handled is True
        assert engine.phase == pytest.approx(0.35)

    def test_offset_quarter_cycle_wraps_phase(self):
        engine = PlaybackEngine(phase=0.9, last_tick=0.0)
        rh_paused = {"value": False}

        handled = apply_runtime_command(
            QUARTER_CYCLE_OFFSET_COMMAND,
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _step: None,
        )

        assert handled is True
        assert engine.phase == pytest.approx(0.15)

    def test_legacy_nudge25_command_still_supported(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}

        handled = apply_runtime_command(
            LEGACY_QUARTER_CYCLE_OFFSET_COMMAND,
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _step: None,
        )

        assert handled is True
        assert engine.phase == pytest.approx(0.25)

    def test_pause_sets_paused(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}

        handled = apply_runtime_command(
            "PAUSE",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _step: None,
        )

        assert handled is True
        assert rh_paused["value"] is True

    def test_resume_clears_paused(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": True}

        handled = apply_runtime_command(
            "RESUME",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _step: None,
        )

        assert handled is True
        assert rh_paused["value"] is False

    def test_pause_sets_direct_state_not_playing(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}
        ds = DirectControlState(playing=True)

        apply_runtime_command(
            "PAUSE",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _step: None,
            direct_state=ds,
        )

        assert ds.playing is False

    def test_resume_sets_direct_state_playing(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": True}
        ds = DirectControlState(playing=False)

        apply_runtime_command(
            "RESUME",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _step: None,
            direct_state=ds,
        )

        assert ds.playing is True

    def test_speed_down_decreases_speed(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}
        ds = DirectControlState(playing=True, speed=50)

        handled = apply_runtime_command(
            "SPEED_DOWN",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _step: None,
            direct_state=ds,
        )

        assert handled is True
        assert ds.speed == 45

    def test_slow_down_is_alias_for_speed_down(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}
        ds = DirectControlState(playing=True, speed=50)

        handled = apply_runtime_command(
            "SLOW_DOWN",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _step: None,
            direct_state=ds,
        )

        assert handled is True
        assert ds.speed == 45

    def test_speed_up_increases_speed(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}
        ds = DirectControlState(playing=True, speed=50)

        handled = apply_runtime_command(
            "SPEED_UP",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _step: None,
            direct_state=ds,
        )

        assert handled is True
        assert ds.speed == 55

    def test_amplitude_down_decreases_amplitude(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}
        ds = DirectControlState(playing=True, amplitude=80)

        handled = apply_runtime_command(
            "AMPLITUDE_DOWN",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _step: None,
            direct_state=ds,
        )

        assert handled is True
        assert ds.amplitude == 70

    def test_amplitude_up_increases_amplitude(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}
        ds = DirectControlState(playing=True, amplitude=80)

        handled = apply_runtime_command(
            "AMPLITUDE_UP",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _step: None,
            direct_state=ds,
        )

        assert handled is True
        assert ds.amplitude == 90

    def test_center_down_decreases_center(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}
        ds = DirectControlState(playing=True, intended_center=50, amplitude=40)

        handled = apply_runtime_command(
            "CENTER_DOWN",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _step: None,
            direct_state=ds,
        )

        assert handled is True
        assert ds.intended_center == 45

    def test_center_up_increases_center(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}
        ds = DirectControlState(playing=True, intended_center=50, amplitude=40)

        handled = apply_runtime_command(
            "CENTER_UP",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _step: None,
            direct_state=ds,
        )

        assert handled is True
        assert ds.intended_center == 55

    def test_cycle_shape_advances_shape(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}
        ds = DirectControlState(playing=True)
        assert ds.shape == WaveformShape.SINE

        handled = apply_runtime_command(
            "CYCLE_SHAPE",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _step: None,
            direct_state=ds,
        )

        assert handled is True
        assert ds.shape == WaveformShape.TRIANGLE

    def test_cycle_shape_prev_reverses_shape(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}
        ds = DirectControlState(playing=True)
        assert ds.shape == WaveformShape.SINE

        handled = apply_runtime_command(
            "CYCLE_SHAPE_PREV",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _step: None,
            direct_state=ds,
        )

        assert handled is True
        assert ds.shape == WaveformShape.SAWTOOTH  # SINE wraps backward to SAWTOOTH

    def test_toggle_cruise_activates_cruise_control(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}
        auto = CruiseControlState(active=False)

        handled = apply_runtime_command(
            "TOGGLE_CRUISE",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _step: None,
            cruise_control_state=auto,
        )

        assert handled is True
        assert auto.active is True

    def test_direct_commands_ignored_without_direct_state(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}

        for cmd in ("SPEED_DOWN", "SPEED_UP", "AMPLITUDE_DOWN", "AMPLITUDE_UP",
                     "CENTER_DOWN", "CENTER_UP", "CYCLE_SHAPE"):
            handled = apply_runtime_command(
                cmd,
                engine=engine,
                rh_paused=rh_paused,
                step_clip=lambda _step: None,
            )
            assert handled is False, f"{cmd} should be ignored without direct_state"

    def test_toggle_cruise_ignored_without_cruise_control_state(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}

        handled = apply_runtime_command(
            "TOGGLE_CRUISE",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _step: None,
        )

        assert handled is False

    def test_cruise_on_enables_cruise_control(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}
        cc = CruiseControlState(active=False)

        handled = apply_runtime_command(
            "CRUISE_ON",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _step: None,
            cruise_control_state=cc,
        )

        assert handled is True
        assert cc.active is True

    def test_cruise_off_disables_cruise_control(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}
        cc = CruiseControlState(active=True)

        handled = apply_runtime_command(
            "CRUISE_OFF",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _step: None,
            cruise_control_state=cc,
        )

        assert handled is True
        assert cc.active is False

    def test_cruise_on_off_ignored_without_cruise_control_state(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}

        for cmd in ("CRUISE_ON", "CRUISE_OFF"):
            handled = apply_runtime_command(
                cmd,
                engine=engine,
                rh_paused=rh_paused,
                step_clip=lambda _step: None,
            )
            assert handled is False, f"{cmd} should be ignored without cruise_control_state"

    def test_amp_sets_amplitude(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}
        ds = DirectControlState(playing=True, amplitude=80)

        handled = apply_runtime_command(
            "AMP 50",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _step: None,
            direct_state=ds,
        )

        assert handled is True
        assert ds.amplitude == 50

    def test_center_sets_center(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}
        ds = DirectControlState(playing=True, intended_center=50, amplitude=40)

        handled = apply_runtime_command(
            "CENTER 80",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _step: None,
            direct_state=ds,
        )

        assert handled is True
        assert ds.intended_center == 80

    def test_speed_sets_speed(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}
        ds = DirectControlState(playing=True, speed=50)

        handled = apply_runtime_command(
            "SPEED 30",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _step: None,
            direct_state=ds,
        )

        assert handled is True
        assert ds.speed == 30

    def test_numeric_commands_ignored_without_direct_state(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}

        for cmd in ("AMP 50", "CENTER 80", "SPEED 30"):
            handled = apply_runtime_command(
                cmd,
                engine=engine,
                rh_paused=rh_paused,
                step_clip=lambda _step: None,
            )
            assert handled is False, f"{cmd} should be ignored without direct_state"

    def test_numeric_command_with_non_integer_is_ignored(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}
        ds = DirectControlState(playing=True)

        handled = apply_runtime_command(
            "AMP abc",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _step: None,
            direct_state=ds,
        )

        assert handled is False

    def test_quit_sets_stop_event(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}
        stop = threading.Event()

        handled = apply_runtime_command(
            "QUIT",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _step: None,
            stop_event=stop,
        )

        assert handled is True
        assert stop.is_set()

    def test_quit_ignored_without_stop_event(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}

        handled = apply_runtime_command(
            "QUIT",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _step: None,
        )

        assert handled is False

    def test_unknown_command_is_ignored(self):
        engine = PlaybackEngine(phase=0.4, last_tick=0.0)
        rh_paused = {"value": False}
        steps: list[int] = []

        handled = apply_runtime_command(
            "UNKNOWN",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=steps.append,
        )

        assert handled is False
        assert engine.phase == 0.4
        assert rh_paused["value"] is False
        assert steps == []

    def test_hud_on_activates_hud_state(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}
        hud = {"active": False}

        handled = apply_runtime_command(
            "HUD_ON",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _step: None,
            hud_state=hud,
        )

        assert handled is True
        assert hud["active"] is True

    def test_hud_off_deactivates_hud_state(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}
        hud = {"active": True}

        handled = apply_runtime_command(
            "HUD_OFF",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _step: None,
            hud_state=hud,
        )

        assert handled is True
        assert hud["active"] is False

    def test_hud_commands_ignored_without_hud_state(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}

        for cmd in ("HUD_ON", "HUD_OFF"):
            handled = apply_runtime_command(
                cmd,
                engine=engine,
                rh_paused=rh_paused,
                step_clip=lambda _step: None,
            )
            assert handled is False, f"{cmd} should be ignored without hud_state"

    def test_display_off_marks_genau_not_the_active_display(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}
        display = {"active": True}

        handled = apply_runtime_command(
            "DISPLAY_OFF",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _step: None,
            display_state=display,
        )

        assert handled is True
        assert display["active"] is False

    def test_display_on_marks_genau_the_active_display(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}
        display = {"active": False}

        handled = apply_runtime_command(
            "DISPLAY_ON",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _step: None,
            display_state=display,
        )

        assert handled is True
        assert display["active"] is True

    def test_display_commands_do_not_touch_playback(self):
        """DISPLAY_* is about what's painted, not whether the hand strokes:
        a paused hand stays paused and a running one keeps running."""
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": True}
        direct = DirectControlState(playing=False)
        display = {"active": True}

        apply_runtime_command(
            "DISPLAY_OFF",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _step: None,
            direct_state=direct,
            display_state=display,
        )

        assert rh_paused["value"] is True
        assert direct.playing is False

    def test_display_commands_ignored_without_display_state(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}

        for cmd in ("DISPLAY_ON", "DISPLAY_OFF"):
            handled = apply_runtime_command(
                cmd,
                engine=engine,
                rh_paused=rh_paused,
                step_clip=lambda _step: None,
            )
            assert handled is False, f"{cmd} should be ignored without display_state"
