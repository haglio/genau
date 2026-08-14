from __future__ import annotations

from player_core.tcode import HANDOFF_MS

from player_core.direct_control import DirectControlState, WaveformShape
from genau.tcode import RateLimitedTCodeSender


class FakeTCodeSink:
    def __init__(self):
        self.sent: list[str] = []
        self.closed = False

    def send(self, command: str) -> None:
        self.sent.append(command)

    def close(self) -> None:
        self.closed = True


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
        # Past the glide a fresh sender opens with, so this is an ordinary tick
        # rather than the ease onto a device somebody else was holding.
        sender.maybe_send(phase=0.0, now=1.0)
        sender.maybe_send(phase=0.25, now=1.5)
        sender.maybe_send(phase=0.5, now=1.55)
        # Third command should have I50 (50ms elapsed)
        assert "I50" in sink.sent[2]


class TestTakingOver:
    """Genau does not hold the device the whole time — in Hybrid a funscript has
    it for every scripted stretch — so it comes back to a device parked wherever
    that script left it, with its own phase run on without it."""

    def test_a_fresh_sender_eases_onto_the_device(self):
        """Whatever had it last — the broker's park, a funscript — it is not
        where this stroke's phase says to be."""
        sink = FakeTCodeSink()
        sender = RateLimitedTCodeSender(sink, min_interval=0.033)

        sender.maybe_send(phase=0.0, now=0.05)

        assert f"I{HANDOFF_MS}" in sink.sent[0]

    def test_taking_the_device_back_eases_onto_it_again(self):
        sink = FakeTCodeSink()
        sender = RateLimitedTCodeSender(sink, min_interval=0.033)
        sender.maybe_send(phase=0.0, now=0.05)
        sender.maybe_send(phase=0.25, now=1.0)

        sender.take_over()
        sender.maybe_send(phase=0.5, now=1.05)

        assert f"I{HANDOFF_MS}" in sink.sent[2]

    def test_every_tick_of_the_glide_is_stretched_not_just_the_first(self):
        """A stroke sends thirty times a second: one stretched command would be
        superseded a frame later by an ordinary one, and the device would cover
        whatever was left of the gap in that frame — the jolt, moved."""
        sink = FakeTCodeSink()
        sender = RateLimitedTCodeSender(sink, min_interval=0.033)

        sender.take_over()
        sender.maybe_send(phase=0.0, now=0.05)
        sender.maybe_send(phase=0.1, now=0.10)
        sender.maybe_send(phase=0.2, now=0.15)

        assert all(f"I{HANDOFF_MS}" in command for command in sink.sent)

    def test_the_stroke_is_its_own_again_once_the_glide_runs_out(self):
        """A glide, not a slowed-down stroke."""
        sink = FakeTCodeSink()
        sender = RateLimitedTCodeSender(sink, min_interval=0.033)
        glide = HANDOFF_MS / 1000

        sender.take_over()
        sender.maybe_send(phase=0.0, now=0.05)
        sender.maybe_send(phase=0.5, now=0.05 + glide + 0.01)
        sender.maybe_send(phase=0.6, now=0.05 + glide + 0.06)

        assert "I50" in sink.sent[2]

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


class TestRestingAtTheBottom:
    """The funscript's turn leaves the device at its park, so the stroke resumes
    from the foot of its swing — phase 0, where every shape's raw value is 0 —
    instead of lunging to wherever the swing happened to freeze."""

    def test_taking_over_resumes_at_the_foot_of_the_swing(self):
        sink = FakeTCodeSink()
        sender = RateLimitedTCodeSender(sink, min_interval=0.0)
        sender.maybe_send(phase=0.5, now=1.0)   # swing at the tip when it froze

        sender.take_over()
        sender.maybe_send(phase=0.5, now=1.05)  # engine phase held through the pause

        assert sink.sent[1].startswith("L00000")

    def test_losing_the_device_rests_the_published_stroke_too(self):
        """The readout Nau draws through a funscript's turn samples forward from
        ``stroke_phase`` — rested at the bottom the moment Genau loses the
        device, so the waiting stroke on screen is the one that will resume."""
        sink = FakeTCodeSink()
        sender = RateLimitedTCodeSender(sink, min_interval=0.0)
        sender.maybe_send(phase=0.5, now=1.0)
        assert sender.current_position() == 9999   # frozen at the tip without this

        sender.rest_at_bottom()

        assert sender.stroke_phase == 0.0
        assert sender.current_position() == 0


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
