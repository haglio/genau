from __future__ import annotations

import random

from genau.auto_pilot import AutoPilotState, tick_auto_pilot, toggle_auto_pilot
from genau.direct_control import DirectControlState, WaveformShape


class TestToggleAutoPilot:
    def test_inactive_to_active(self):
        state = AutoPilotState(rng=random.Random(42))
        toggle_auto_pilot(state)
        assert state.active is True

    def test_active_to_inactive(self):
        state = AutoPilotState(active=True, rng=random.Random(42))
        toggle_auto_pilot(state)
        assert state.active is False


class TestTickAutoPilotInactive:
    def test_does_not_change_direct_state_when_inactive(self):
        dc = DirectControlState(speed_level=5, amplitude=80, center=50)
        auto = AutoPilotState(active=False, rng=random.Random(42))
        tick_auto_pilot(dc, auto, now=10.0)
        assert dc.speed_level == 5
        assert dc.amplitude == 80
        assert dc.center == 50


class TestTickAutoPilotActive:
    def test_changes_parameters_over_time(self):
        dc = DirectControlState(speed_level=5, amplitude=80, center=50, shape=WaveformShape.SINE)
        auto = AutoPilotState(active=True, rng=random.Random(42))
        # Initialize timing
        tick_auto_pilot(dc, auto, now=0.0)
        original = (dc.speed_level, dc.amplitude, dc.center, dc.shape)
        # Tick forward enough for all parameters to have changed
        for i in range(200):
            tick_auto_pilot(dc, auto, now=0.1 * (i + 1))
        current = (dc.speed_level, dc.amplitude, dc.center, dc.shape)
        assert current != original

    def test_amplitude_stays_in_range(self):
        dc = DirectControlState(amplitude=50)
        auto = AutoPilotState(active=True, rng=random.Random(42))
        tick_auto_pilot(dc, auto, now=0.0)
        for i in range(500):
            tick_auto_pilot(dc, auto, now=0.05 * (i + 1))
        assert 0 <= dc.amplitude <= 100

    def test_center_stays_in_range(self):
        dc = DirectControlState(center=50)
        auto = AutoPilotState(active=True, rng=random.Random(42))
        tick_auto_pilot(dc, auto, now=0.0)
        for i in range(500):
            tick_auto_pilot(dc, auto, now=0.05 * (i + 1))
        assert 0 <= dc.center <= 100

    def test_speed_stays_in_range(self):
        dc = DirectControlState(speed_level=5)
        auto = AutoPilotState(active=True, rng=random.Random(42))
        tick_auto_pilot(dc, auto, now=0.0)
        for i in range(500):
            tick_auto_pilot(dc, auto, now=0.05 * (i + 1))
        assert 1 <= dc.speed_level <= 10

    def test_shape_is_valid(self):
        dc = DirectControlState()
        auto = AutoPilotState(active=True, rng=random.Random(42))
        tick_auto_pilot(dc, auto, now=0.0)
        for i in range(200):
            tick_auto_pilot(dc, auto, now=0.1 * (i + 1))
        assert dc.shape in list(WaveformShape)
