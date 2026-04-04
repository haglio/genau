from __future__ import annotations

import pytest

from genau.direct_control import (
    DirectControlState,
    bpm_for_speed_level,
    phase_to_position,
    set_speed,
    toggle_playing,
)


class TestBpmForSpeedLevel:
    def test_level_1_returns_minimum_bpm(self):
        assert bpm_for_speed_level(1) == pytest.approx(30.0)

    def test_level_10_returns_maximum_bpm(self):
        assert bpm_for_speed_level(10) == pytest.approx(200.0)

    def test_monotonically_increasing(self):
        bpms = [bpm_for_speed_level(i) for i in range(1, 11)]
        for i in range(len(bpms) - 1):
            assert bpms[i] < bpms[i + 1]


class TestTogglePlaying:
    def test_false_to_true(self):
        state = DirectControlState()
        toggle_playing(state)
        assert state.playing is True

    def test_true_to_false(self):
        state = DirectControlState(playing=True)
        toggle_playing(state)
        assert state.playing is False


class TestSetSpeed:
    def test_sets_level_and_bpm(self):
        state = DirectControlState()
        set_speed(state, 3)
        assert state.speed_level == 3
        assert state.bpm == pytest.approx(bpm_for_speed_level(3))

    def test_clamps_below_1(self):
        state = DirectControlState()
        set_speed(state, 0)
        assert state.speed_level == 1

    def test_clamps_above_10(self):
        state = DirectControlState()
        set_speed(state, 11)
        assert state.speed_level == 10


class TestPhaseToPosition:
    def test_phase_0_returns_center(self):
        assert phase_to_position(0.0) == 5000

    def test_phase_quarter_returns_max(self):
        assert phase_to_position(0.25) == 9999

    def test_phase_half_returns_center(self):
        assert phase_to_position(0.5) == pytest.approx(5000, abs=1)

    def test_phase_three_quarter_returns_min(self):
        assert phase_to_position(0.75) == pytest.approx(1, abs=1)

    def test_result_always_in_range(self):
        for p in [0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 0.999]:
            pos = phase_to_position(p)
            assert 0 <= pos <= 9999
