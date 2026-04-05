from __future__ import annotations

import random

from genau.cruise_control import CruiseControlState, tick_cruise_control, toggle_cruise_control
from genau.direct_control import DirectControlState, WaveformShape


class TestToggleCruiseControl:
    def test_inactive_to_active(self):
        state = CruiseControlState(rng=random.Random(42))
        toggle_cruise_control(state)
        assert state.active is True

    def test_active_to_inactive(self):
        state = CruiseControlState(active=True, rng=random.Random(42))
        toggle_cruise_control(state)
        assert state.active is False


class TestTickCruiseControlInactive:
    def test_does_not_change_direct_state_when_inactive(self):
        dc = DirectControlState(speed=50, amplitude=80, intended_center=50)
        auto = CruiseControlState(active=False, rng=random.Random(42))
        tick_cruise_control(dc, auto, now=10.0)
        assert dc.speed == 50
        assert dc.amplitude == 80
        assert dc.center == 50


class TestTickCruiseControlActive:
    def test_changes_parameters_over_time(self):
        dc = DirectControlState(speed=50, amplitude=80, intended_center=50, shape=WaveformShape.SINE)
        auto = CruiseControlState(active=True, rng=random.Random(42))
        # Initialize timing
        tick_cruise_control(dc, auto, now=0.0)
        original_speed = dc.speed
        # Tick forward enough for all parameters to have changed
        for i in range(200):
            tick_cruise_control(dc, auto, now=0.1 * (i + 1))
        # At least one parameter should have changed
        changed = (
            dc.speed != original_speed
            or dc.amplitude != 80
            or dc.center != 50
            or dc.shape is not WaveformShape.SINE
        )
        assert changed

    def test_amplitude_stays_in_range(self):
        dc = DirectControlState(amplitude=50)
        auto = CruiseControlState(active=True, rng=random.Random(42))
        tick_cruise_control(dc, auto, now=0.0)
        for i in range(500):
            tick_cruise_control(dc, auto, now=0.05 * (i + 1))
        assert 0 <= dc.amplitude <= 100

    def test_center_stays_in_range(self):
        dc = DirectControlState(center=50)
        auto = CruiseControlState(active=True, rng=random.Random(42))
        tick_cruise_control(dc, auto, now=0.0)
        for i in range(500):
            tick_cruise_control(dc, auto, now=0.05 * (i + 1))
        assert 0 <= dc.center <= 100

    def test_speed_stays_in_range(self):
        dc = DirectControlState(speed=50)
        auto = CruiseControlState(active=True, rng=random.Random(42))
        tick_cruise_control(dc, auto, now=0.0)
        for i in range(500):
            tick_cruise_control(dc, auto, now=0.05 * (i + 1))
        assert 0 <= dc.speed <= 100

    def test_shape_is_valid(self):
        dc = DirectControlState()
        auto = CruiseControlState(active=True, rng=random.Random(42))
        tick_cruise_control(dc, auto, now=0.0)
        for i in range(200):
            tick_cruise_control(dc, auto, now=0.1 * (i + 1))
        assert dc.shape in list(WaveformShape)


class TestCruiseControlClipAdvance:
    def test_advances_clip_after_interval(self):
        dc = DirectControlState()
        auto = CruiseControlState(active=True, rng=random.Random(42))
        calls = []
        step_clip = lambda delta: calls.append(delta)
        tick_cruise_control(dc, auto, now=0.0, step_clip=step_clip)
        # Tick past the clip interval (~8-12s range)
        for i in range(150):
            tick_cruise_control(dc, auto, now=0.1 * (i + 1), step_clip=step_clip)
        assert len(calls) >= 1
        assert all(c == 1 for c in calls)

    def test_does_not_advance_when_inactive(self):
        dc = DirectControlState()
        auto = CruiseControlState(active=False, rng=random.Random(42))
        calls = []
        step_clip = lambda delta: calls.append(delta)
        for i in range(150):
            tick_cruise_control(dc, auto, now=0.1 * i, step_clip=step_clip)
        assert calls == []

    def test_no_error_without_step_clip(self):
        dc = DirectControlState()
        auto = CruiseControlState(active=True, rng=random.Random(42))
        tick_cruise_control(dc, auto, now=0.0)
        for i in range(150):
            tick_cruise_control(dc, auto, now=0.1 * (i + 1))
        # Should complete without error when step_clip is None
