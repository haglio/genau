"""A failing tick, said once rather than a hundred times a second.

refresh() wraps the whole tick and logs the traceback, and the main loop calls
it again immediately at up to 120fps.  A persistent fault -- a missing status
directory, a broken drive file, a None the tick did not expect -- therefore
wrote thousands of identical tracebacks a second into genau_listener.log, which
both buries the first occurrence and can fill the state directory the other
three IPC files live in.
"""
from __future__ import annotations

import logging

import pytest

from genau.tick_failures import TickFailures


@pytest.fixture
def said(caplog):
    caplog.set_level(logging.DEBUG, logger="test.tick")
    return caplog


def _failures() -> TickFailures:
    return TickFailures(logging.getLogger("test.tick"))


def _levels(caplog) -> list[str]:
    return [record.levelname for record in caplog.records]


class TestTheFirstOfAKind:
    def test_it_is_reported_with_its_traceback(self, said):
        failures = _failures()

        failures.failed(RuntimeError("the tick broke"))

        assert _levels(said) == ["ERROR"]
        assert said.records[0].exc_info is not None
        assert "the tick broke" in said.text

    def test_a_second_kind_is_reported_with_its_own(self, said):
        failures = _failures()
        failures.failed(RuntimeError("the tick broke"))

        failures.failed(ValueError("something else"))

        assert _levels(said) == ["ERROR", "ERROR"]
        assert "something else" in said.text

    def test_the_same_class_carrying_a_different_message_is_a_second_kind(self, said):
        """Two faults of one class are still two faults; the message is what
        tells a missing status directory from a missing drive file."""
        failures = _failures()
        failures.failed(OSError("no such file: genau_status.txt"))

        failures.failed(OSError("no such file: genau_drive.txt"))

        assert _levels(said) == ["ERROR", "ERROR"]


class TestTheSameOneAgain:
    def test_it_is_not_reported_again_at_error(self, said):
        failures = _failures()
        failures.failed(RuntimeError("the tick broke"))

        for _ in range(500):
            failures.failed(RuntimeError("the tick broke"))

        assert _levels(said) == ["ERROR"] + ["DEBUG"] * 500

    def test_the_repeats_carry_no_traceback(self, said):
        """The traceback is the expensive part and it is already on the log."""
        failures = _failures()
        failures.failed(RuntimeError("the tick broke"))
        failures.failed(RuntimeError("the tick broke"))

        assert said.records[-1].exc_info is None


class TestWhenItStops:
    def test_a_tick_that_works_says_how_many_were_swallowed(self, said):
        failures = _failures()
        failures.failed(RuntimeError("the tick broke"))
        for _ in range(4):
            failures.failed(RuntimeError("the tick broke"))

        failures.worked()

        assert _levels(said)[-1] == "ERROR"
        assert "4" in said.records[-1].getMessage()

    def test_a_single_failure_that_recovers_says_nothing_more(self, said):
        """One bad tick in a session is a traceback, not a report about itself."""
        failures = _failures()
        failures.failed(RuntimeError("the tick broke"))

        failures.worked()

        assert _levels(said) == ["ERROR"]

    def test_a_tick_that_works_from_the_start_says_nothing(self, said):
        _failures().worked()

        assert said.records == []

    def test_the_next_failure_after_a_recovery_is_reported_again(self, said):
        """Even the same one: a fault that comes back after the app recovered is
        news, and its traceback may be from a different place."""
        failures = _failures()
        failures.failed(RuntimeError("the tick broke"))
        failures.worked()

        failures.failed(RuntimeError("the tick broke"))

        assert _levels(said) == ["ERROR", "ERROR"]

    def test_a_new_kind_arriving_says_how_many_the_old_one_swallowed(self, said):
        """Otherwise the count is lost whenever one fault gives way to another,
        which is exactly when a session is coming apart."""
        failures = _failures()
        failures.failed(RuntimeError("the tick broke"))
        for _ in range(9):
            failures.failed(RuntimeError("the tick broke"))

        failures.failed(ValueError("something else"))

        summary = [r.getMessage() for r in said.records if "9" in r.getMessage()]
        assert summary
