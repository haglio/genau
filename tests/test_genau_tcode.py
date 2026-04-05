from __future__ import annotations

from genau.direct_control import DirectControlState, WaveformShape
from genau.tcode import RateLimitedTCodeSender, UdpTCodeSink, format_tcode_command


class FakeSock:
    def __init__(self):
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.closed = False

    def sendto(self, data: bytes, addr: tuple[str, int]) -> None:
        self.sent.append((data, addr))

    def close(self) -> None:
        self.closed = True


class TestUdpTCodeSink:
    def test_send_transmits_newline_terminated_ascii_datagram(self):
        sock = FakeSock()
        sink = UdpTCodeSink(host="127.0.0.1", port=50557, sock=sock)
        sink.send("L05000I33")
        assert sock.sent == [(b"L05000I33\n", ("127.0.0.1", 50557))]

    def test_close_closes_socket(self):
        sock = FakeSock()
        sink = UdpTCodeSink(sock=sock)
        sink.close()
        assert sock.closed is True

    def test_defaults(self):
        sock = FakeSock()
        sink = UdpTCodeSink(sock=sock)
        sink.send("L09999I50")
        assert sock.sent == [(b"L09999I50\n", ("127.0.0.1", 50557))]


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


class TestSenderWithDirectState:
    def test_reads_amplitude_from_state(self):
        sink = FakeTCodeSink()
        state = DirectControlState(amplitude=50, center=50)
        sender = RateLimitedTCodeSender(sink, direct_state=state, min_interval=0.0)
        sender.maybe_send(phase=0.5, now=1.0)
        # amplitude=50, center=50: tip should be ~7500, not 9999
        pos_value = int(sink.sent[0][2:6])
        assert 7000 < pos_value < 8000

    def test_reads_shape_from_state(self):
        sink = FakeTCodeSink()
        state = DirectControlState(shape=WaveformShape.TRIANGLE)
        sender = RateLimitedTCodeSender(sink, direct_state=state, min_interval=0.0)
        sender.maybe_send(phase=0.25, now=1.0)
        # Triangle at 0.25 should be 5000 (same as sine at 0.25 for default params)
        pos_value = int(sink.sent[0][2:6])
        assert 4900 < pos_value < 5100

    def test_current_position(self):
        sink = FakeTCodeSink()
        state = DirectControlState()
        sender = RateLimitedTCodeSender(sink, direct_state=state, min_interval=0.0)
        sender.maybe_send(phase=0.5, now=1.0)
        assert sender.current_position() == 9999

    def test_send_park_sends_position_100_percent(self):
        sink = FakeTCodeSink()
        sender = RateLimitedTCodeSender(sink, min_interval=0.0)
        sender.send_park()
        assert sink.sent == ["L00000I500"]

    def test_send_park_custom_interval(self):
        sink = FakeTCodeSink()
        sender = RateLimitedTCodeSender(sink, min_interval=0.0)
        sender.send_park(interval_ms=1000)
        assert sink.sent == ["L00000I1000"]

