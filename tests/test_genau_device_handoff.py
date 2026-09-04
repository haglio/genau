"""The device changing hands, both directions.

The sender is told on the edge to climb out of the park or walk the stroke down
and rest it.  The tick used to hold this inline, interleaved with ten other
jobs, with the previous play state as a bare attribute beside them.
"""
from __future__ import annotations

from genau.device_handoff import DeviceHandoff


class FakeSender:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def take_over(self) -> None:
        self.calls.append("take_over")

    def hand_over(self) -> None:
        self.calls.append("hand_over")


class TestTheSender:
    def test_a_hand_that_starts_moving_arms_the_climb_out_of_the_park(self):
        sender = FakeSender()
        handoff = DeviceHandoff(playing=False, tcode_sender=sender)

        handoff.watch(True)

        assert sender.calls == ["take_over"]

    def test_a_hand_that_stops_walks_the_stroke_down_and_rests_it(self):
        sender = FakeSender()
        handoff = DeviceHandoff(playing=True, tcode_sender=sender)

        handoff.watch(False)

        assert sender.calls == ["hand_over"]

    def test_it_is_the_edge_and_not_the_state_that_is_acted_on(self):
        """Told the same thing twice, the second says nothing: the walk down
        latches where the device was, and doing it again would move the latch."""
        sender = FakeSender()
        handoff = DeviceHandoff(playing=True, tcode_sender=sender)

        handoff.watch(False)
        handoff.watch(False)
        handoff.watch(False)

        assert sender.calls == ["hand_over"]

    def test_the_first_tick_reads_against_the_state_it_was_built_in(self):
        """A PAUSE queued before the first tick is a real falling edge; seeded
        the other way it would either be missed or fire on nothing."""
        sender = FakeSender()

        DeviceHandoff(playing=True, tcode_sender=sender).watch(True)

        assert sender.calls == []

    def test_a_build_with_no_sender_still_follows_the_edge(self):
        handoff = DeviceHandoff(playing=False)

        handoff.watch(True)   # must not raise
        handoff.watch(False)
