from __future__ import annotations

from nau.funscript import Funscript
from nau.tcode_driver import FunscriptTCodeDriver


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

    def test_speed_up_shortens_move_duration(self):
        sink = FakeSink()
        driver = FunscriptTCodeDriver(sink)

        # At t=0 the next waypoint (1000, 100) is 1000ms away in *media* time,
        # but at 2x playback the video reaches it in 500ms of wall-clock, so the
        # OSR2 must complete its move in 500ms to stay in sync.
        driver.update(0, self._make_fs(), now=0.0, speed=2.0)

        assert sink.sent[0] == "L09999I500"

    def test_slow_down_lengthens_move_duration(self):
        sink = FakeSink()
        driver = FunscriptTCodeDriver(sink)

        # At 0.5x the waypoint is 2000ms of wall-clock away, so the move stretches.
        driver.update(0, self._make_fs(), now=0.0, speed=0.5)

        assert sink.sent[0] == "L09999I2000"

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


class TestLeadInPark:
    def _lead_in_fs(self):
        # Isolated blip at t=0, then dense action from 60s: onset = 60000.
        return Funscript(actions=[(0, 50), (60000, 0), (60300, 100), (60600, 0)])

    def test_parks_at_closest_position_during_lead_in(self):
        sink = FakeSink()
        driver = FunscriptTCodeDriver(sink)

        driver.update(10000, self._lead_in_fs(), now=0.0)

        # Rest at position 0 (closest), the same place the broker parks on pause.
        assert sink.sent == ["L00000I500"]

    def test_resumes_normal_driving_at_first_real_event(self):
        sink = FakeSink()
        driver = FunscriptTCodeDriver(sink)
        fs = self._lead_in_fs()

        driver.update(10000, fs, now=0.0)   # parked during lead-in
        driver.update(60000, fs, now=1.0)   # onset reached: drive normally

        # Park, then the next waypoint aims at (60300, 100). Remaining = 300ms.
        assert sink.sent == ["L00000I500", "L09999I300"]

    def test_park_is_rate_limited_but_resends(self):
        sink = FakeSink()
        driver = FunscriptTCodeDriver(sink)
        fs = self._lead_in_fs()

        driver.update(10000, fs, now=0.0)    # first park send
        driver.update(11000, fs, now=0.05)   # within resend interval: suppressed
        driver.update(12000, fs, now=0.15)   # past resend interval: resends

        assert sink.sent == ["L00000I500", "L00000I500"]


class TestPark:
    """park() rests the OSR2 at its closest position with no funscript in play —
    an unscripted video.  It reuses the lead-in rest's waypoint and edge gating,
    so callers can hold the device parked without a script to drive from."""

    def test_sends_closest_position(self):
        sink = FakeSink()
        driver = FunscriptTCodeDriver(sink)

        driver.park(now=0.0)

        # Position 0 (closest), the same place the broker parks on pause.
        assert sink.sent == ["L00000I500"]

    def test_edge_gated_then_resends(self):
        sink = FakeSink()
        driver = FunscriptTCodeDriver(sink)

        driver.park(now=0.0)   # first send
        driver.park(now=0.05)  # within the resend interval: suppressed
        driver.park(now=0.15)  # past the resend interval: resends

        assert sink.sent == ["L00000I500", "L00000I500"]
