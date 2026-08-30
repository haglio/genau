"""What GenauVR actually puts on the wire, and where it puts it.

``UdpTCodeSink`` and ``RateLimitedTCodeSender`` are the whole path from a
playback phase to the packets the OSR2 broker acts on, and nothing constructed
either one: the port could be off by one — pointing the headset's stroke at
nothing, or at another listener — and every test stayed green.

The port is a family contract (50557, the same number broker and fun_time use),
which is why it is written down here as a literal rather than read back out of
the module that would be wrong.
"""
from __future__ import annotations

from genau_vr.config import VrConfig
from genau_vr.playback import (
    DirectControlState,
    RateLimitedTCodeSender,
    UdpTCodeSink,
    WaveformShape,
    format_tcode_command,
)


class RecordingSocket:
    """A datagram socket that keeps what it was asked to send, and to whom."""

    def __init__(self) -> None:
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.closed = False

    def sendto(self, payload: bytes, address: tuple[str, int]) -> None:
        self.sent.append((payload, address))

    def close(self) -> None:
        self.closed = True


class RecordingSink:
    """The commands a sender emitted, in order."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.closed = False

    def send(self, command: str) -> None:
        self.sent.append(command)

    def close(self) -> None:
        self.closed = True


class TestTheWireFormat:
    def test_a_command_names_the_axis_the_position_and_how_long_to_take(self):
        assert format_tcode_command("L0", 5000, 33) == "L05000I33"

    def test_the_position_is_four_digits_however_small(self):
        """The device reads fixed-width fields, so a short number is a
        different position rather than a rejected command."""
        assert format_tcode_command("L0", 7, 33) == "L00007I33"

    def test_a_position_past_the_top_of_the_range_is_the_top(self):
        assert format_tcode_command("L0", 99999, 33) == "L09999I33"

    def test_a_position_below_the_range_is_the_bottom(self):
        assert format_tcode_command("L0", -500, 33) == "L00000I33"

    def test_a_negative_interval_asks_for_no_time_rather_than_for_less_than_none(self):
        """A clock that went backwards would otherwise put a minus sign in the
        middle of the command, which the device cannot read at all."""
        assert format_tcode_command("L0", 5000, -20) == "L05000I0"


class TestTheUdpSink:
    def test_it_sends_to_the_host_and_port_it_was_given(self):
        sock = RecordingSocket()
        sink = UdpTCodeSink("10.0.0.4", 51000, sock=sock)

        sink.send("L05000I33")

        assert sock.sent == [(b"L05000I33\n", ("10.0.0.4", 51000))]

    def test_it_defaults_to_the_port_the_rest_of_the_family_listens_on(self):
        """50557 is the broker's, and fun_time's, and Genau's own.  A sink that
        opened on 50558 would send into nothing and say nothing about it."""
        sock = RecordingSocket()

        UdpTCodeSink(sock=sock).send("L00000I1")

        assert sock.sent[0][1] == ("127.0.0.1", 50557)

    def test_the_config_default_names_the_same_endpoint(self, tmp_path):
        """The two ways GenauVR can arrive at an endpoint have to agree, or a
        config with no T-Code section drives a different device than one with."""
        assert VrConfig(state_dir=tmp_path).tcode_endpoint == ("127.0.0.1", 50557)

    def test_closing_the_sink_closes_the_socket(self):
        sock = RecordingSocket()
        sink = UdpTCodeSink(sock=sock)

        sink.close()

        assert sock.closed


def _sender(sink, **state) -> RateLimitedTCodeSender:
    """A sender over *sink*, driving a stroke with the given shape and range."""
    return RateLimitedTCodeSender(
        sink, direct_state=DirectControlState(**state), min_interval=0.0)


class TestHowOftenItSends:
    def test_the_first_tick_always_sends(self):
        sink = RecordingSink()
        sender = RateLimitedTCodeSender(sink, min_interval=0.033)

        sender.maybe_send(phase=0.0, now=0.05)

        assert len(sink.sent) == 1

    def test_a_tick_inside_the_interval_sends_nothing(self):
        """60fps of stroke into a device that reads 30 is half the packets
        wasted, and the device's queue is what backs up."""
        sink = RecordingSink()
        sender = RateLimitedTCodeSender(sink, min_interval=0.033)
        sender.maybe_send(phase=0.0, now=0.05)

        sender.maybe_send(phase=0.01, now=0.06)

        assert len(sink.sent) == 1

    def test_a_tick_past_the_interval_sends_again(self):
        sink = RecordingSink()
        sender = RateLimitedTCodeSender(sink, min_interval=0.033)
        sender.maybe_send(phase=0.0, now=0.05)

        sender.maybe_send(phase=0.1, now=0.1)

        assert len(sink.sent) == 2

    def test_the_command_asks_for_the_time_since_the_last_one(self):
        """The interval is the device's whole instruction about pace: it is
        told where to be and how long it has to get there."""
        sink = RecordingSink()
        sender = RateLimitedTCodeSender(sink, min_interval=0.033)
        sender.maybe_send(phase=0.0, now=0.05)

        sender.maybe_send(phase=0.25, now=0.10)

        assert sink.sent[1].endswith("I50")


class TestWhereTheStrokeIsSentTo:
    """The position is the waveform read at the accumulated stroke phase, inside
    the range amplitude and centre leave it."""

    def test_the_foot_of_a_full_swing_is_the_bottom_of_the_range(self):
        sink = RecordingSink()

        _sender(sink, amplitude=100, intended_center=50).maybe_send(phase=0.0, now=1.0)

        assert sink.sent[0].startswith("L00000")

    def test_the_top_of_a_full_swing_is_the_top_of_the_range(self):
        sink = RecordingSink()
        sender = _sender(sink, amplitude=100, intended_center=50)

        sender.maybe_send(phase=0.5, now=1.0)

        assert sink.sent[0].startswith("L09999")

    def test_a_narrowed_amplitude_narrows_both_ends(self):
        """Half the travel, centred: the swing runs the middle quarter to
        three-quarters of the range rather than all of it."""
        sink = RecordingSink()
        sender = _sender(sink, amplitude=50, intended_center=50)

        sender.maybe_send(phase=0.0, now=1.0)
        sender.maybe_send(phase=0.5, now=2.0)

        assert [c.split("I")[0] for c in sink.sent] == ["L02500", "L07499"]

    def test_a_raised_centre_lifts_the_whole_swing(self):
        sink = RecordingSink()
        sender = _sender(sink, amplitude=40, intended_center=70)

        sender.maybe_send(phase=0.0, now=1.0)
        sender.maybe_send(phase=0.5, now=2.0)

        assert [c.split("I")[0] for c in sink.sent] == ["L04999", "L08999"]


class TestTheStrokePhaseTheSenderKeeps:
    """The engine's phase wraps at 1.0; the stroke's does not.

    SAWTOOTH throughout, because it is the one shape that is not symmetric
    about its peak — under SINE or TRIANGLE, phase 0.4 and phase 0.6 send the
    device to the same place, and a test written on one of those cannot see the
    stroke moving the wrong way.
    """

    def test_the_stroke_carries_on_forward_across_a_wrap(self):
        """0.99 to 0.01 is one frame of ordinary motion, not a rewind of almost
        a whole cycle."""
        sink = RecordingSink()
        sender = _sender(sink, shape=WaveformShape.SAWTOOTH)
        sender.maybe_send(phase=0.99, now=1.0)

        sender.maybe_send(phase=0.01, now=2.0)

        before, after = (int(c[2:6]) for c in sink.sent)
        assert after > before, "the wrap read as a rewind and the stroke stalled"

    def test_a_phase_nudged_backwards_does_not_drag_the_stroke_back(self):
        """The engine pulls its phase back onto the beat whenever a sync pulse
        arrives.  The device must not be walked backwards for it — it is where
        it is, and the stroke goes on from there."""
        sink = RecordingSink()
        sender = _sender(sink, shape=WaveformShape.SAWTOOTH)
        sender.maybe_send(phase=0.6, now=1.0)

        sender.maybe_send(phase=0.4, now=2.0)

        assert sink.sent[1][:6] == sink.sent[0][:6]

    def test_closing_the_sender_closes_the_sink_under_it(self):
        sink = RecordingSink()
        sender = RateLimitedTCodeSender(sink)

        sender.close()

        assert sink.closed
