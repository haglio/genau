from __future__ import annotations

from nau.funscript import Funscript
from nau.tcode_driver import (
    FunscriptTCodeDriver,
    UdpTCodeSink,
    format_tcode_command,
)


class TestFormatTCodeCommand:
    def test_basic_format(self):
        assert format_tcode_command("L0", 5000, 33) == "L05000I33"

    def test_clamps_position(self):
        assert format_tcode_command("L0", 10500, 33) == "L09999I33"
        assert format_tcode_command("L0", -1, 33) == "L00000I33"


class FakeSink:
    def __init__(self):
        self.sent: list[str] = []

    def send(self, command: str) -> None:
        self.sent.append(command)

    def close(self) -> None:
        pass


class TestFunscriptTCodeDriver:
    def _make_fs(self):
        return Funscript(actions=[(0, 0), (1000, 100), (2000, 0)])

    def test_sends_next_waypoint_on_first_update(self):
        sink = FakeSink()
        driver = FunscriptTCodeDriver(sink)

        driver.update(0, self._make_fs(), now=0.0)

        assert len(sink.sent) == 1
        # At t=0, next waypoint is (1000, 100). Remaining = 1000ms.
        assert sink.sent[0] == "L09999I1000"

    def test_remaining_time_shrinks_mid_segment(self):
        sink = FakeSink()
        driver = FunscriptTCodeDriver(sink)

        driver.update(500, self._make_fs(), now=0.0)

        # At t=500, next waypoint is (1000, 100). Remaining = 500ms.
        assert sink.sent[0] == "L09999I500"

    def test_no_duplicate_in_same_segment(self):
        sink = FakeSink()
        driver = FunscriptTCodeDriver(sink)
        fs = self._make_fs()

        driver.update(0, fs, now=0.0)
        driver.update(500, fs, now=0.05)

        assert len(sink.sent) == 1

    def test_new_segment_triggers_send(self):
        sink = FakeSink()
        driver = FunscriptTCodeDriver(sink)
        fs = self._make_fs()

        driver.update(0, fs, now=0.0)
        driver.update(1001, fs, now=1.0)

        assert len(sink.sent) == 2
        # At t=1001, next waypoint is (2000, 0). Remaining = 999ms.
        assert sink.sent[1] == "L00000I999"

    def test_reset_allows_resend_in_same_segment(self):
        sink = FakeSink()
        driver = FunscriptTCodeDriver(sink)
        fs = self._make_fs()

        driver.update(0, fs, now=0.0)
        driver.reset()
        driver.update(100, fs, now=0.1)

        assert len(sink.sent) == 2

    def test_past_last_action_holds_position(self):
        sink = FakeSink()
        driver = FunscriptTCodeDriver(sink)
        fs = Funscript(actions=[(0, 0), (1000, 50)])

        driver.update(1500, fs, now=0.0)

        assert sink.sent[0] == "L05000I100"

    def test_periodic_resend_protects_against_packet_loss(self):
        sink = FakeSink()
        driver = FunscriptTCodeDriver(sink)
        # One long segment: 0 to 10000ms
        fs = Funscript(actions=[(0, 0), (10000, 100)])

        driver.update(0, fs, now=0.0)
        driver.update(500, fs, now=0.5)  # same segment, 500ms later

        assert len(sink.sent) == 2
