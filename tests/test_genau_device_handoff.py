"""The device changing hands, both directions.

Two things happen on the edge and neither is symmetric with the other: the
sender is told to climb out of the park or walk the stroke down and rest it, and
the broker is told to resume or park.  The tick used to hold both inline,
interleaved with ten other jobs, with the previous play state as a bare
attribute beside them.
"""
from __future__ import annotations

from pathlib import Path

import pytest

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


class TestTheBroker:
    def test_a_hand_that_starts_moving_says_resume(self, tmp_path):
        cmd = tmp_path / "broker_cmd.txt"

        DeviceHandoff(playing=False, broker_cmd_file=cmd).watch(True)

        assert cmd.read_text(encoding="utf-8") == "RESUME"

    def test_a_hand_that_stops_says_park(self, tmp_path):
        cmd = tmp_path / "broker_cmd.txt"

        DeviceHandoff(playing=True, broker_cmd_file=cmd).watch(False)

        assert cmd.read_text(encoding="utf-8") == "PARK"

    def test_no_edge_writes_nothing_at_all(self, tmp_path):
        """Written every tick it would be a file rewritten 120 times a second
        for a fact that changes twice a session."""
        cmd = tmp_path / "broker_cmd.txt"

        DeviceHandoff(playing=True, broker_cmd_file=cmd).watch(True)

        assert not cmd.exists()

    def test_a_build_where_the_orchestrator_owns_the_handoff_writes_nothing(self):
        """Under Fun Time the orchestrator parks the broker itself; Genau must
        not also, or the two fight over one device."""
        DeviceHandoff(playing=False).watch(True)   # must not raise


class TestBothHalvesOnOneEdge:
    @pytest.mark.parametrize(
        "was, now, said, written",
        [(False, True, "take_over", "RESUME"), (True, False, "hand_over", "PARK")],
    )
    def test_the_sender_and_the_broker_are_told_together(
        self, was, now, said, written, tmp_path,
    ):
        sender = FakeSender()
        cmd = tmp_path / "broker_cmd.txt"

        DeviceHandoff(playing=was, tcode_sender=sender, broker_cmd_file=cmd).watch(now)

        assert sender.calls == [said]
        assert cmd.read_text(encoding="utf-8") == written


def test_the_broker_file_is_a_path_not_a_name(tmp_path):
    """It is handed the path an orchestrator named, and writes nowhere else."""
    cmd = tmp_path / "nested" / "broker_cmd.txt"
    cmd.parent.mkdir()

    DeviceHandoff(playing=False, broker_cmd_file=Path(cmd)).watch(True)

    assert cmd.read_text(encoding="utf-8") == "RESUME"
