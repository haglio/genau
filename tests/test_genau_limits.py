"""Which of the hand's arrows would do nothing — computed once, published twice.

The status file Fun Time reads and the drive readout Nau draws are two
publications of one fact, and they used to work it out separately: the same six
booleans and the same `half = amplitude // 2` centre clamp, in two modules, with
a comment in one of them naming the duplication.  A change to the clamp had to
be made in both or the console dimmed an arrow the status file called live.
"""
from __future__ import annotations

import pytest

from genau.limits import control_limits
from player_core.direct_control import MAX_SPEED, MIN_SPEED, DirectControlState


def _limits(**state):
    return control_limits(DirectControlState(**state))


class TestTheTravelEnds:
    def test_a_travel_at_the_top_dims_only_the_up_arrow(self):
        limits = _limits(amplitude=100)

        assert (limits.amp_at_max, limits.amp_at_min) == (True, False)

    def test_a_travel_at_the_bottom_dims_only_the_down_arrow(self):
        limits = _limits(amplitude=0)

        assert (limits.amp_at_max, limits.amp_at_min) == (False, True)

    def test_a_travel_in_between_dims_neither(self):
        limits = _limits(amplitude=60)

        assert (limits.amp_at_max, limits.amp_at_min) == (False, False)


class TestTheCentreIsClampedByTheTravel:
    """The centre cannot push a stroke off the top or bottom of the device, so
    the range it has is what the travel leaves it: half the travel in from each
    end.  This is the rule the two publications used to spell out separately."""

    @pytest.mark.parametrize(
        "amplitude, at_max, at_min",
        [
            # A 60 travel leaves the centre 30..70.
            (60, 70, 30),
            # A full travel leaves it nowhere to go: 50 is both ends at once.
            (100, 50, 50),
            # No travel at all leaves the whole axis.
            (0, 100, 0),
        ],
    )
    def test_the_range_is_half_the_travel_in_from_each_end(
        self, amplitude, at_max, at_min,
    ):
        top = _limits(amplitude=amplitude, center=at_max, intended_center=at_max)
        bottom = _limits(amplitude=amplitude, center=at_min, intended_center=at_min)

        assert top.ctr_at_max is True
        assert bottom.ctr_at_min is True

    def test_a_centre_inside_that_range_dims_neither(self):
        limits = _limits(amplitude=60, center=50, intended_center=50)

        assert (limits.ctr_at_max, limits.ctr_at_min) == (False, False)

    def test_a_full_travel_dims_both_at_once(self):
        limits = _limits(amplitude=100, center=50, intended_center=50)

        assert (limits.ctr_at_max, limits.ctr_at_min) == (True, True)


class TestTheSpeed:
    def test_the_fastest_dims_only_the_up_arrow(self):
        limits = _limits(speed=MAX_SPEED)

        assert (limits.spd_at_max, limits.spd_at_min) == (True, False)

    def test_the_slowest_dims_only_the_down_arrow(self):
        limits = _limits(speed=MIN_SPEED)

        assert (limits.spd_at_max, limits.spd_at_min) == (False, True)

    def test_a_speed_between_them_dims_neither(self):
        limits = _limits(speed=(MIN_SPEED + MAX_SPEED) // 2)

        assert (limits.spd_at_max, limits.spd_at_min) == (False, False)


class TestBothPublicationsReadTheSameSix:
    """The point of the type: what the status file says and what the console
    draws cannot disagree, because there is one answer."""

    HANDS = [
        {},
        {"amplitude": 100},
        {"amplitude": 0},
        {"speed": MAX_SPEED},
        {"speed": MIN_SPEED},
        {"amplitude": 60, "center": 70, "intended_center": 70},
        {"amplitude": 60, "center": 30, "intended_center": 30},
    ]

    @pytest.mark.parametrize("hand", HANDS, ids=[str(sorted(h)) for h in HANDS])
    def test_the_status_file_says_what_the_readout_was_told(self, hand):
        from genau.status_writer import build_status_text
        from player_core.cruise_control import CruiseControlState

        direct = DirectControlState(**hand)
        limits = control_limits(direct)
        said = dict(
            line.split("=", 1)
            for line in build_status_text(direct, CruiseControlState()).splitlines()
        )

        for field in ("amp_at_max", "amp_at_min", "ctr_at_max", "ctr_at_min",
                      "spd_at_max", "spd_at_min"):
            assert said[field] == ("1" if getattr(limits, field) else "0"), field
