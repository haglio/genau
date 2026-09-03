"""Tilting the picture with the thumbstick.

A rate rather than an amount: how fast the picture turns while the stick is
held.  It lived in the frame loop as a local and a deadzone comparison with two
unnamed numbers on the line beside it.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from genau_vr.pitch import (
    PITCH_LIMIT_RAD,
    PITCH_RATE_RAD_PER_S,
    THUMBSTICK_DEADZONE,
    PitchControl,
)


class TestTheDeadzone:
    def test_a_resting_stick_leaves_the_picture_alone(self):
        """A resting stick reports small non-zero values, and without this the
        picture drifts on its own."""
        pitch = PitchControl()

        pitch.follow(THUMBSTICK_DEADZONE, dt=1.0)

        assert pitch.offset == 0.0

    def test_a_stick_just_past_it_turns_the_picture(self):
        pitch = PitchControl()

        pitch.follow(THUMBSTICK_DEADZONE + 0.01, dt=1.0)

        assert pitch.offset != 0.0

    def test_it_is_the_size_of_the_push_and_not_its_direction(self):
        pitch = PitchControl()

        pitch.follow(-THUMBSTICK_DEADZONE, dt=1.0)

        assert pitch.offset == 0.0


class TestHowFarItTurns:
    def test_a_full_push_for_one_second_turns_by_the_rate(self):
        pitch = PitchControl()

        pitch.follow(-1.0, dt=1.0)

        assert pitch.offset == pytest.approx(PITCH_RATE_RAD_PER_S)

    def test_half_a_second_turns_half_as_far(self):
        pitch = PitchControl()

        pitch.follow(-1.0, dt=0.5)

        assert pitch.offset == pytest.approx(PITCH_RATE_RAD_PER_S / 2)

    def test_pushing_forward_tilts_the_picture_down(self):
        """Which is what makes the world appear to rotate the way the stick is
        pushed rather than against it."""
        pitch = PitchControl()

        pitch.follow(1.0, dt=1.0)

        assert pitch.offset < 0

    def test_holding_it_goes_on_turning(self):
        pitch = PitchControl()

        pitch.follow(-1.0, dt=0.5)
        pitch.follow(-1.0, dt=0.5)

        assert pitch.offset == pytest.approx(PITCH_RATE_RAD_PER_S)


class TestItStopsAtStraightUpAndStraightDown:
    """Past either the picture would be upside down."""

    def test_it_will_not_turn_past_straight_up(self):
        pitch = PitchControl()

        pitch.follow(-1.0, dt=60.0)

        assert pitch.offset == pytest.approx(PITCH_LIMIT_RAD)

    def test_it_will_not_turn_past_straight_down(self):
        pitch = PitchControl()

        pitch.follow(1.0, dt=60.0)

        assert pitch.offset == pytest.approx(-PITCH_LIMIT_RAD)

    def test_a_stick_held_at_the_limit_can_still_come_back(self):
        pitch = PitchControl()
        pitch.follow(-1.0, dt=60.0)

        pitch.follow(1.0, dt=0.5)

        assert pitch.offset < PITCH_LIMIT_RAD


class TestTheMatrixItHandsTheEyes:
    def test_an_untilted_picture_hands_over_nothing(self):
        """None rather than an identity matrix, so an untilted frame skips a
        matrix multiply per eye per frame."""
        assert PitchControl().matrix() is None

    def test_a_tilted_one_hands_over_the_rotation_for_its_offset(self):
        from genau_vr.projection import pitch_rotation_matrix

        pitch = PitchControl(offset=math.pi / 3)

        assert pitch.matrix() == pytest.approx(pitch_rotation_matrix(math.pi / 3))

    def test_the_rotation_follows_the_offset_as_it_moves(self):
        pitch = PitchControl()
        pitch.follow(-1.0, dt=1.0)

        turned = pitch.matrix() @ np.array([0.0, 1.0, 0.0, 1.0], dtype=np.float32)

        assert turned[2] > 0    # up has swung toward the axis pointing away
