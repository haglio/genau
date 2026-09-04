"""Cruise control: the stroke varying itself while nobody is driving.

Every case here sets the targets and the schedule outright and leaves the rng
alone, so what is asserted is the movement rather than a particular draw.  The
one thing a seeded rng is used for is the two decisions that are genuinely a
coin toss -- which way the speed steps, and which shape comes next.
"""
from __future__ import annotations

import random

import pytest

from genau_vr.cruise_control import (
    CruiseControlState,
    disable_cruise_control,
    enable_cruise_control,
    tick_cruise_control,
    toggle_cruise_control,
)
from genau_vr.playback import RobotHandState, WaveformShape

# Far enough ahead that nothing is due; a case that wants a thing to happen
# brings that one thing's clock back.
NEVER = 10_000.0


def _cruising(**over) -> CruiseControlState:
    """An active state whose schedule is entirely in the future."""
    fields = dict(active=True, _last_tick=1.0, _next_retarget=NEVER,
                  _next_speed_change=NEVER, _next_shape_change=NEVER,
                  rng=random.Random(0))
    fields.update(over)
    return CruiseControlState(**fields)


def _stroke(**over) -> RobotHandState:
    fields = dict(amplitude=100, intended_center=50, speed=50,
                  shape=WaveformShape.SINE)
    fields.update(over)
    return RobotHandState(**fields)


class TestTurningItOnAndOff:
    def test_it_starts_off(self):
        assert CruiseControlState().active is False

    def test_toggling_walks_between_the_two(self):
        state = CruiseControlState()

        toggle_cruise_control(state)
        assert state.active is True

        toggle_cruise_control(state)
        assert state.active is False

    def test_it_can_be_asked_for_by_name_rather_than_toggled(self):
        """The spoken forms are "cruise on" and "cruise off": a speaker asks for
        the state they want, not for the other one."""
        state = CruiseControlState()

        enable_cruise_control(state)
        assert state.active is True

        disable_cruise_control(state)
        assert state.active is False


class TestATickThatDoesNothing:
    def test_nothing_moves_while_cruise_is_off(self):
        stroke, cruise = _stroke(), _cruising(active=False, _next_retarget=0.0,
                                              _next_speed_change=0.0,
                                              _next_shape_change=0.0)

        tick_cruise_control(stroke, cruise, now=1.1)

        assert (stroke.amplitude, stroke.speed, stroke.shape) == (
            100, 50, WaveformShape.SINE)

    def test_a_clock_that_went_backwards_moves_nothing(self):
        stroke = _stroke()
        cruise = _cruising(_amplitude_target=30.0)

        tick_cruise_control(stroke, cruise, now=0.5)

        assert stroke.amplitude == 100

    def test_a_gap_too_long_to_be_a_frame_moves_nothing(self):
        """A second is many frames: the app was blocked, or is only now
        starting, and lerping by that dt would jump the device."""
        stroke = _stroke()
        cruise = _cruising(_amplitude_target=30.0)

        tick_cruise_control(stroke, cruise, now=3.0)

        assert stroke.amplitude == 100

    def test_but_the_clock_still_starts_so_the_next_tick_lands(self):
        stroke = _stroke()
        cruise = _cruising(_amplitude_target=30.0)

        tick_cruise_control(stroke, cruise, now=3.0)
        tick_cruise_control(stroke, cruise, now=3.1)

        assert stroke.amplitude == 85


class TestTheSwingDrifting:
    def test_the_amplitude_travels_toward_its_target(self):
        """A fifth of the way in a tenth of a second, snapped to a multiple of
        five -- the resolution the controls themselves move in."""
        stroke = _stroke(amplitude=100)
        cruise = _cruising(_amplitude_target=30.0)

        tick_cruise_control(stroke, cruise, now=1.1)

        assert stroke.amplitude == 85

    def test_the_center_travels_toward_its_own(self):
        stroke = _stroke(intended_center=50)
        cruise = _cruising(_center_target=80.0)

        tick_cruise_control(stroke, cruise, now=1.1)

        assert stroke.intended_center == 55

    def test_it_keeps_going_tick_after_tick(self):
        stroke = _stroke(amplitude=100)
        cruise = _cruising(_amplitude_target=30.0)

        for tick in range(1, 6):
            tick_cruise_control(stroke, cruise, now=1.0 + tick / 10)

        assert stroke.amplitude == 55

    def test_the_reachable_center_follows_the_swing_it_is_inside(self):
        """The two move together, so a drifting amplitude cannot leave the
        center somewhere the swing would run off the end from."""
        stroke = _stroke(amplitude=40, intended_center=80)
        cruise = _cruising(_amplitude_target=100.0, _center_target=80.0)

        tick_cruise_control(stroke, cruise, now=1.1)

        assert stroke.center == 100 - stroke.amplitude // 2

    def test_a_target_it_has_reached_holds_it_there(self):
        stroke = _stroke(amplitude=50)
        cruise = _cruising(_amplitude_target=50.0)

        tick_cruise_control(stroke, cruise, now=1.1)

        assert stroke.amplitude == 50


class TestWhatOnlyHappensWhenItIsDue:
    def test_the_speed_holds_until_its_own_clock_comes_round(self):
        stroke, cruise = _stroke(speed=50), _cruising(_amplitude_target=30.0)

        tick_cruise_control(stroke, cruise, now=1.1)

        assert stroke.speed == 50

    def test_and_then_steps_one_notch(self):
        stroke = _stroke(speed=50)
        cruise = _cruising(_next_speed_change=0.0)

        tick_cruise_control(stroke, cruise, now=1.1)

        assert stroke.speed in (45, 55)

    def test_a_step_taken_puts_the_next_one_out_of_reach(self):
        stroke = _stroke(speed=50)
        cruise = _cruising(_next_speed_change=0.0)
        tick_cruise_control(stroke, cruise, now=1.1)
        stepped_to = stroke.speed

        tick_cruise_control(stroke, cruise, now=1.2)

        assert stroke.speed == stepped_to

    def test_the_shape_holds_until_its_own_clock_comes_round(self):
        stroke, cruise = _stroke(), _cruising()

        tick_cruise_control(stroke, cruise, now=1.1)

        assert stroke.shape is WaveformShape.SINE

    def test_and_then_becomes_the_one_the_seeded_draw_names(self):
        """A case saying only "one of the four" is true of the shape it already
        had, so the whole branch could be deleted under it.  Seeded, the draw is
        a fact: this rng picks SAWTOOTH."""
        stroke = _stroke(shape=WaveformShape.SINE)
        cruise = _cruising(_next_shape_change=0.0)

        tick_cruise_control(stroke, cruise, now=1.1)

        assert stroke.shape is WaveformShape.SAWTOOTH
        assert cruise._next_shape_change > 1.1 + 5.0, "and the next one is scheduled"

    def test_the_targets_are_re_drawn_inside_the_range_they_are_allowed(self):
        """Amplitude between 30 and 100, center between 20 and 80 -- the stroke
        wanders without ever going still or running to an end."""
        stroke = _stroke()
        cruise = _cruising(_next_retarget=0.0)
        started_at = (cruise._amplitude_target, cruise._center_target)

        tick_cruise_control(stroke, cruise, now=1.1)

        # Both must MOVE: the dataclass opens on 100.0 and 50.0, which already
        # sit inside the two ranges, so "in range" alone is true of a draw that
        # never happened.
        assert (cruise._amplitude_target, cruise._center_target) != started_at
        assert 30.0 <= cruise._amplitude_target <= 100.0
        assert 20.0 <= cruise._center_target <= 80.0
        assert cruise._next_retarget >= 1.1 + 3.0


def test_cruise_control_never_changes_the_clip():
    """The VR loop owns the clip; cruise varies the stroke and nothing else.

    An older player_core design had cruise advance clips too, and this copy
    was taken from it. genau_vr/app.py:436 calls it with three positional
    arguments and no stepper, so the auto-advance never ran -- VR cruise
    silently never changed clips while reading as if it did.
    """
    with pytest.raises(TypeError):
        tick_cruise_control(_stroke(), _cruising(), 1.1, lambda _delta: None)
