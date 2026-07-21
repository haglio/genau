from __future__ import annotations

import random

from genau.cruise_control import (
    CruiseControlState,
    disable_cruise_control,
    enable_cruise_control,
    tick_cruise_control,
    toggle_cruise_control,
)
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


class TestEnableCruiseControl:
    def test_activates_when_inactive(self):
        state = CruiseControlState(rng=random.Random(42))
        enable_cruise_control(state)
        assert state.active is True

    def test_stays_active_when_already_active(self):
        state = CruiseControlState(active=True, rng=random.Random(42))
        enable_cruise_control(state)
        assert state.active is True


class TestDisableCruiseControl:
    def test_deactivates_when_active(self):
        state = CruiseControlState(active=True, rng=random.Random(42))
        disable_cruise_control(state)
        assert state.active is False

    def test_stays_inactive_when_already_inactive(self):
        state = CruiseControlState(rng=random.Random(42))
        disable_cruise_control(state)
        assert state.active is False


class TestTickCruiseControlInactive:
    def test_does_not_change_direct_state_when_inactive(self):
        dc = DirectControlState(speed=50, amplitude=80, intended_center=50)
        auto = CruiseControlState(active=False, rng=random.Random(42))
        tick_cruise_control(dc, auto, now=10.0)
        assert dc.speed == 50
        assert dc.amplitude == 80
        assert dc.center == 50


class TestTickCruiseControlPaused:
    """Armed but not stroking — paused by hand, frozen under OmniPause, or sitting
    out a funscript's turn in Hybrid.  Auto advance has always sat still then; this
    used to go on moving the stroke, so a session came back from a pause to a
    stroke it never asked for."""

    def test_a_paused_hand_freezes_the_stroke(self):
        dc = DirectControlState(speed=50, amplitude=80, intended_center=50,
                                shape=WaveformShape.SINE, playing=False)
        cc = CruiseControlState(active=True, rng=random.Random(42))

        tick_cruise_control(dc, cc, now=0.0)
        for i in range(200):
            tick_cruise_control(dc, cc, now=0.1 * (i + 1))

        assert (dc.speed, dc.amplitude, dc.center) == (50, 80, 50)
        assert dc.shape is WaveformShape.SINE

    def test_it_picks_up_where_it_left_off_rather_than_lurching_on_resume(self):
        """The clock keeps up through the pause, so the first tick after it sees a
        normal step — not the whole pause at once, and not a skipped tick."""
        dc = DirectControlState(speed=50, amplitude=80, intended_center=50, playing=False)
        cc = CruiseControlState(active=True, rng=random.Random(42))

        for i in range(100):
            tick_cruise_control(dc, cc, now=0.1 * i)

        assert cc._last_tick == 0.1 * 99


class TestTickCruiseControlActive:
    def test_changes_parameters_over_time(self):
        dc = DirectControlState(speed=50, amplitude=80, intended_center=50,
                                shape=WaveformShape.SINE, playing=True)
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
        dc = DirectControlState(amplitude=50, playing=True)
        auto = CruiseControlState(active=True, rng=random.Random(42))
        tick_cruise_control(dc, auto, now=0.0)
        for i in range(500):
            tick_cruise_control(dc, auto, now=0.05 * (i + 1))
        assert 0 <= dc.amplitude <= 100

    def test_center_stays_in_range(self):
        dc = DirectControlState(center=50, playing=True)
        auto = CruiseControlState(active=True, rng=random.Random(42))
        tick_cruise_control(dc, auto, now=0.0)
        for i in range(500):
            tick_cruise_control(dc, auto, now=0.05 * (i + 1))
        assert 0 <= dc.center <= 100

    def test_speed_stays_in_range(self):
        dc = DirectControlState(speed=50, playing=True)
        auto = CruiseControlState(active=True, rng=random.Random(42))
        tick_cruise_control(dc, auto, now=0.0)
        for i in range(500):
            tick_cruise_control(dc, auto, now=0.05 * (i + 1))
        assert 0 <= dc.speed <= 100

    def test_shape_is_valid(self):
        dc = DirectControlState(playing=True)
        auto = CruiseControlState(active=True, rng=random.Random(42))
        tick_cruise_control(dc, auto, now=0.0)
        for i in range(200):
            tick_cruise_control(dc, auto, now=0.1 * (i + 1))
        assert dc.shape in list(WaveformShape)
