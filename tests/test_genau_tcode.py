from __future__ import annotations

from genau.tcode import RateLimitedTCodeSender, format_tcode_command


class FakeTCodeSink:
    def __init__(self):
        self.sent: list[str] = []
        self.closed = False

    def send(self, command: str) -> None:
        self.sent.append(command)

    def close(self) -> None:
        self.closed = True


class TestFormatTcodeCommand:
    def test_max_position(self):
        assert format_tcode_command("L0", 9999, 33) == "L09999I33"

    def test_min_position(self):
        assert format_tcode_command("L0", 0, 100) == "L00000I100"

    def test_center_position(self):
        assert format_tcode_command("L0", 5000, 50) == "L05000I50"

    def test_clamps_position_above_max(self):
        assert format_tcode_command("L0", 10500, 33) == "L09999I33"

    def test_clamps_position_below_zero(self):
        assert format_tcode_command("L0", -5, 33) == "L00000I33"


class TestRateLimitedTCodeSender:
    def test_first_call_always_sends(self):
        sink = FakeTCodeSink()
        sender = RateLimitedTCodeSender(sink, min_interval=0.033)
        sender.maybe_send(phase=0.0, now=1.0)
        assert len(sink.sent) == 1

    def test_second_call_within_interval_does_not_send(self):
        sink = FakeTCodeSink()
        sender = RateLimitedTCodeSender(sink, min_interval=0.033)
        sender.maybe_send(phase=0.0, now=1.0)
        sender.maybe_send(phase=0.01, now=1.01)
        assert len(sink.sent) == 1

    def test_second_call_after_interval_sends(self):
        sink = FakeTCodeSink()
        sender = RateLimitedTCodeSender(sink, min_interval=0.033)
        sender.maybe_send(phase=0.0, now=1.0)
        sender.maybe_send(phase=0.1, now=1.05)
        assert len(sink.sent) == 2

    def test_interval_reflects_elapsed_time(self):
        sink = FakeTCodeSink()
        sender = RateLimitedTCodeSender(sink, min_interval=0.033)
        sender.maybe_send(phase=0.0, now=1.0)
        sender.maybe_send(phase=0.25, now=1.05)
        # Second command should have I50 (50ms elapsed)
        assert "I50" in sink.sent[1]

    def test_phase_wrap_accumulates_stroke_phase(self):
        sink = FakeTCodeSink()
        sender = RateLimitedTCodeSender(sink, min_interval=0.0)
        # Phase goes 0.9 → 0.1 (wrap). Stroke phase should go 0.9 → 1.1
        sender.maybe_send(phase=0.9, now=1.0)
        sender.maybe_send(phase=0.1, now=1.05)
        # stroke_phase ~1.1: past the base-at-1.0 point, heading back up.
        # Should NOT snap to the position for raw phase 0.1 (near base).
        # Position at 1.1 should be small but nonzero (~951).
        pos_str = sink.sent[1]
        assert pos_str.startswith("L0")
        pos_value = int(pos_str[2:6])
        assert 500 < pos_value < 2000

    def test_no_wrap_advances_stroke_phase_normally(self):
        sink = FakeTCodeSink()
        sender = RateLimitedTCodeSender(sink, min_interval=0.0)
        sender.maybe_send(phase=0.0, now=1.0)
        sender.maybe_send(phase=0.5, now=1.05)
        # stroke_phase=0.5 → tip (9999) with 2π cosine
        assert "L09999" in sink.sent[1]

    def test_close_delegates_to_sink(self):
        sink = FakeTCodeSink()
        sender = RateLimitedTCodeSender(sink, min_interval=0.033)
        sender.close()
        assert sink.closed is True
