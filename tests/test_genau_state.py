"""Tests for genau.state (SharedState + UDP message parsing)."""
from __future__ import annotations

import dataclasses
import socket
import threading
import logging
from unittest.mock import MagicMock

import pytest

from app_support.threading_utils import wait_until
from genau.state import SharedState, apply_udp_line, udp_reader


# ---------------------------------------------------------------------------
# SharedState defaults
# ---------------------------------------------------------------------------

class TestSharedState:
    def test_it_holds_only_the_fields_something_reads(self):
        """The listener's state is the read surface, not a log of the wire.

        Genau acts on three verbs. The broker also sends SHOW, HIDE, BEATS,
        STROKE and PATTERN, and fields once existed to hold all of them --
        copied into the snapshot every tick and read by nobody. Naming the
        set here is what stops a write-only field growing back.
        """
        assert {f.name for f in dataclasses.fields(SharedState)} == {
            "lock", "auto_active", "raw_bpm", "sync_pulse_id",
        }

    def test_default_values(self):
        s = SharedState()
        assert s.auto_active is False
        assert s.raw_bpm is None
        assert s.sync_pulse_id == 0

    def test_has_lock(self):
        s = SharedState()
        # threading.Lock is a factory function on <=3.12 but a real class on
        # >=3.13, so isinstance against it raises on the older ones. Match the
        # instance type instead, which is a genuine lock type on every version.
        assert isinstance(s.lock, type(threading.Lock()))


# ---------------------------------------------------------------------------
# Helpers: send UDP from a test thread to the udp_reader bound on a free port
# ---------------------------------------------------------------------------

def _free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _send(port: int, msg: str) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(msg.encode(), ("127.0.0.1", port))


# A knock at the door: SYNC is the one verb whose effect only counts, so it says
# "a datagram arrived" without moving anything a case goes on to assert about.
_KNOCK = "SYNC"


def _wait_until_bound(port: int, state: SharedState) -> None:
    """Block until the reader's socket is actually taking datagrams.

    The bind happens inside the thread under test, so there is no moment the
    test can watch for from outside -- and a datagram sent before it lands is
    dropped without a trace rather than queued.  So the knock is re-offered
    until one of them arrives, which is over the instant the socket is up and
    spends the timeout only when it never comes.
    """
    def _knocked() -> bool:
        _send(port, _KNOCK)
        return state.sync_pulse_id > 0

    wait_until(_knocked, timeout=10.0, interval=0.02)


def _turned_away(caplog) -> bool:
    """Whether the reader has logged a bind attempt that failed."""
    return any("bind attempt" in record.getMessage() for record in caplog.records)


def _run_reader(state: SharedState, port: int) -> tuple[threading.Thread, threading.Event]:
    stop = threading.Event()
    logger = logging.getLogger("test.udp_reader")
    t = threading.Thread(target=udp_reader, args=("127.0.0.1", port, state, stop, logger), daemon=True)
    t.start()
    _wait_until_bound(port, state)
    return t, stop


# ---------------------------------------------------------------------------
# UDP message parsing
# ---------------------------------------------------------------------------

class TestActingOnOneLine:
    """The parsing, without a socket.

    Thirteen of the fifteen slowest tests in the repo used to be these cases,
    each binding a real port and sleeping for the datagram to arrive -- about
    nine seconds, and the only wall-clock-dependent tests in the suite.  What
    they were testing is a pure function.
    """

    @staticmethod
    def _applied(line: str, state: SharedState | None = None) -> SharedState:
        state = state if state is not None else SharedState()
        apply_udp_line(state, line, logging.getLogger("test.udp_reader"))
        return state

    def test_auto_1_hands_the_room_to_the_broker(self):
        assert self._applied("AUTO 1").auto_active is True

    def test_auto_0_takes_the_room_back(self):
        state = SharedState(auto_active=True)

        assert self._applied("AUTO 0", state).auto_active is False

    def test_any_other_payload_takes_the_room_back_too(self):
        """The broker says 1 or 0; anything else is not an assertion that it
        owns the room, and taking it back is the safe reading."""
        state = SharedState(auto_active=True)

        assert self._applied("AUTO yes", state).auto_active is False

    def test_bpm_parsed(self):
        assert self._applied("BPM 120.5").raw_bpm == pytest.approx(120.5)

    def test_bpm_invalid_leaves_the_last_one_standing(self):
        """A malformed payload is a lost datagram, not a reason to stop
        following the beat the last good one named."""
        state = SharedState(raw_bpm=120.0)

        assert self._applied("BPM notanumber", state).raw_bpm == 120.0

    def test_bpm_invalid_is_said_on_the_log(self, caplog):
        with caplog.at_level("WARNING", logger="test.udp_reader"):
            self._applied("BPM notanumber")

        assert "notanumber" in caplog.text

    def test_sync_increments(self):
        state = SharedState()

        self._applied("SYNC", state)
        self._applied("SYNC", state)

        assert state.sync_pulse_id == 2

    def test_a_lower_case_verb_is_the_same_verb(self):
        assert self._applied("auto 1").auto_active is True

    @pytest.mark.parametrize("line", [
        "SHOW", "HIDE", "BEATS 4", "STROKE twist", "PATTERN 2.5", "UNKNOWN payload",
        "", "   ",
    ])
    def test_a_verb_genau_does_not_act_on_leaves_the_state_where_it_was(self, line):
        """The broker still sends SHOW, HIDE, BEATS, STROKE and PATTERN.

        Genau acts on AUTO, BPM and SYNC. The other five arrive and fall
        through exactly as an unrecognized line does -- no crash, nothing
        moved. Whether the broker should stop sending them is the broker's
        call, not this reader's.
        """
        state = self._applied(line)

        assert (state.auto_active, state.raw_bpm, state.sync_pulse_id) == (False, None, 0)

    def test_the_state_is_moved_under_its_own_lock(self):
        """The reader runs on its own thread and the tick reads the same three
        fields; every other writer holds this lock."""
        state = SharedState()
        held: list[str] = []
        original = state.lock

        class _Recording:
            def __enter__(self):
                held.append("taken")
                return original.__enter__()

            def __exit__(self, *exc):
                held.append("given back")
                return original.__exit__(*exc)

        state.lock = _Recording()
        apply_udp_line(state, "SYNC", logging.getLogger("test.udp_reader"))

        assert held == ["taken", "given back"]


class TestTheSocketLoop:
    """What is left needing a real port: that the wire reaches the parsing, and
    that the bind gives the port time to free.

    Every wait here is on something the reader itself did -- a datagram it
    answered, a warning it logged, a thread it left -- rather than on a nap long
    enough to have probably happened.  A nap is both slower than it needs to be
    and a coin flip on a loaded runner.
    """

    def test_a_datagram_on_the_wire_reaches_the_state(self):
        state = SharedState()
        port = _free_udp_port()
        t, stop = _run_reader(state, port)
        try:
            _send(port, "AUTO 1")
            wait_until(lambda: state.auto_active, timeout=10.0, interval=0.02)
        finally:
            stop.set()
            t.join(timeout=1.0)

        assert state.auto_active is True

    def test_stop_event_terminates_reader(self):
        state = SharedState()
        port = _free_udp_port()
        t, stop = _run_reader(state, port)
        stop.set()
        t.join(timeout=2.0)
        assert not t.is_alive()

    def test_bind_retries_on_port_conflict(self, caplog):
        """The port is held when the reader starts, and free by its next attempt.

        The blocker deliberately does NOT set SO_REUSEADDR: Windows lets two
        sockets share a port when both ask for it -- and the reader asks -- so a
        blocker that asked was no blocker there at all, the first bind
        succeeded, and this proved nothing on the one platform the gate runs on.

        The release is driven by the reader's own "bind attempt failed" warning
        rather than by a nap, so the port is freed once it has actually been
        turned away, however slow the machine is.
        """
        state = SharedState()
        port = _free_udp_port()

        blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        blocker.bind(("127.0.0.1", port))

        stop = threading.Event()
        logger = logging.getLogger("test.udp_reader")
        t = threading.Thread(
            target=udp_reader,
            args=("127.0.0.1", port, state, stop, logger),
            # Many short waits rather than a few long ones: the port is freed
            # the moment the reader's first refusal is logged, so a short delay
            # gets it bound at once, and the length of the list is only how long
            # a stalled machine may take to get there before the retries run out.
            kwargs={"retry_delays": (0.02,) * 500},
            daemon=True,
        )
        try:
            with caplog.at_level(logging.WARNING):
                t.start()
                wait_until(lambda: _turned_away(caplog), timeout=10.0)
                blocker.close()

                _wait_until_bound(port, state)
                _send(port, "AUTO 1")
                wait_until(lambda: state.auto_active, timeout=10.0, interval=0.02)
        finally:
            stop.set()
            blocker.close()
            t.join(timeout=2.0)

        assert state.auto_active is True

    def test_bind_failure_gives_up_and_says_so_on_the_log(self):
        """A port that never frees ends the reader, with the reason logged.

        The log is the whole report: nothing in Genau reads a failure off the
        shared state, so a listener that cannot bind is a log line and a
        thread that has stopped.

        The schedule is three zero-length waits, because what is under test is
        what happens once the retries run out, not how long they take getting
        there.
        """
        state = SharedState()
        port = _free_udp_port()

        # Occupy the port for the entire duration — don't release it
        blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        blocker.bind(("127.0.0.1", port))

        stop = threading.Event()
        logger = MagicMock()
        t = threading.Thread(
            target=udp_reader,
            args=("127.0.0.1", port, state, stop, logger),
            kwargs={"retry_delays": (0, 0, 0)},
            daemon=True,
        )
        t.start()
        try:
            t.join(timeout=8.0)
            assert not t.is_alive()
            logger.exception.assert_called_once_with("UDP reader failed")
        finally:
            stop.set()
            blocker.close()
            t.join(timeout=2.0)
