"""What of Genau's publish this video's picture believes, and for how long.

Two things the gate holds across frames: the descent forecasts, chosen once and
held, and whether Genau has been seen live in *this* video yet.

The forecasts are watched through the touch-down the status file publishes —
``handoff_touch`` answers out of the same latch — and the question every case
below asks is the same one: a newer publish has arrived, so is the choice made
for this boundary still the one that was made first, or has it been made again?
Held, the wave underneath can move as much as it likes and the answer does not;
voided, the fresh wave gets to answer.

The stroke used throughout rests its floor ON the park (full amplitude,
centred), because only such a stroke has a touch-down at all; a raised floor
ramps down instead and has none to publish.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from player_core.drive_readout import TRACE_SAMPLES, DriveHud
from player_core.funscript import Funscript

from nau.drive_gate import DriveGate

SPAN_S = 7.9
STEP_MS = 100
FIRST_VIDEO = Path("videos/Jane Doe - scene one.mp4")
SECOND_VIDEO = Path("videos/Ann Bly - scene two.mp4")
# The touch the trace chooses for the boundary ahead, on the first read.
CHOSEN_TOUCH_MS = 3_600
# How much newer the second publish is.  Deliberately not equal to any playhead
# a case moves to: a wave advanced by exactly as much as the playhead reads the
# same in absolute time, and a re-choice off one would land back on the first
# answer and look like a carry.
NEWER_MS = 200


def _stroke(ms: int = 0, **over) -> DriveHud:
    """Genau's publish, *ms* into the video: the same wave, phase advanced."""
    steps = ms / STEP_MS
    base = dict(
        speed=50, amplitude=100, center=50, trace_seconds=SPAN_S,
        waveform=tuple(0.5 - 0.5 * np.cos((i + steps) / 6) for i in range(TRACE_SAMPLES)))
    base.update(over)
    return DriveHud(**base)


def _script() -> Funscript:
    """A script whose one cluster is still ahead of the playhead, so the handoff
    into it is inside the drawn window."""
    return Funscript(actions=[(t, 0 if (t // 200) % 2 else 100)
                              for t in range(8_000, 9_001, 200)])


class FakeSession:
    """What the gate reads off the player: where it is, in what, how fast."""

    def __init__(self) -> None:
        self.current_funscript = _script()
        self.current_video = FIRST_VIDEO
        self.position_ms = 0.0
        self.speed = 1.0


def _gate_holding_a_forecast() -> tuple[DriveGate, FakeSession]:
    """A gate that has read once and chosen a touch for the boundary ahead."""
    session = FakeSession()
    gate = DriveGate(session)
    gate.readout(_stroke(), genau_behind=True)
    assert gate.handoff_touch() == CHOSEN_TOUCH_MS
    return gate, session


def _a_newer_publish_arrives(gate: DriveGate) -> None:
    gate.readout(_stroke(NEWER_MS), genau_behind=True)


class TestChoosingAForecast:
    def test_the_trace_chooses_a_touch_down_for_the_boundary_ahead(self):
        gate = DriveGate(FakeSession())

        gate.readout(_stroke(), genau_behind=True)

        assert gate.handoff_touch() == CHOSEN_TOUCH_MS

    def test_with_no_stroke_published_there_is_nothing_to_choose_from(self):
        gate = DriveGate(FakeSession())

        gate.readout(None, genau_behind=True)

        assert gate.handoff_touch() is None


class TestAChoiceThatIsHeld:
    """Re-read live every frame, the top breathed with the beat between Genau's
    publish cadence and the frame clock, and the seam flickered between "blue
    ends on the park" and a slightly diagonal ramp."""

    def test_a_newer_publish_does_not_move_it(self):
        gate, _session = _gate_holding_a_forecast()

        _a_newer_publish_arrives(gate)

        assert gate.handoff_touch() == CHOSEN_TOUCH_MS

    def test_a_frames_worth_of_playing_does_not_move_it(self):
        gate, session = _gate_holding_a_forecast()

        session.position_ms = 40
        _a_newer_publish_arrives(gate)

        assert gate.handoff_touch() == CHOSEN_TOUCH_MS

    def test_a_stall_too_short_to_be_a_pause_does_not_move_it(self):
        """The trace's 40ms quantum makes some real frames read as zero."""
        gate, session = _gate_holding_a_forecast()
        for _ in range(5):
            gate.readout(_stroke(), genau_behind=True)

        session.position_ms = 40
        _a_newer_publish_arrives(gate)

        assert gate.handoff_touch() == CHOSEN_TOUCH_MS

    def test_a_pause_still_running_does_not_move_it(self):
        """The choice goes when the playhead moves again, not while it waits:
        the picture on a paused player is the one it was already showing."""
        gate, _session = _gate_holding_a_forecast()

        for _ in range(40):
            _a_newer_publish_arrives(gate)

        assert gate.handoff_touch() == CHOSEN_TOUCH_MS


class TestWhatVoidsAChoice:
    """Every one of these means the wave the choice was cut from has stopped
    describing this approach, so the fresh wave gets to answer instead."""

    def test_a_stint_with_nobody_behind_the_screen(self):
        """Nau's own mode: the wave keeps moving while nothing here watches it,
        so every held forecast is void by the time it could be read again."""
        gate, _session = _gate_holding_a_forecast()

        gate.readout(_stroke(), genau_behind=False)
        _a_newer_publish_arrives(gate)

        assert gate.handoff_touch() != CHOSEN_TOUCH_MS

    def test_a_different_video(self):
        gate, session = _gate_holding_a_forecast()

        session.current_video = SECOND_VIDEO
        _a_newer_publish_arrives(gate)

        assert gate.handoff_touch() != CHOSEN_TOUCH_MS

    def test_a_rewind(self):
        """The carry rules are written for one continuous approach, and a
        rewind approaches the SAME boundary again with a realigned wave -- the
        old choice's touch then cuts the new wave anywhere, which is how the
        blue once overran its own drawn ending by a whole cycle."""
        gate, session = _gate_holding_a_forecast()

        session.position_ms = -300
        _a_newer_publish_arrives(gate)

        assert gate.handoff_touch() != CHOSEN_TOUCH_MS

    def test_a_jump_forward(self):
        gate, session = _gate_holding_a_forecast()

        session.position_ms = 900
        _a_newer_publish_arrives(gate)

        assert gate.handoff_touch() != CHOSEN_TOUCH_MS

    def test_the_end_of_a_pause_long_enough_to_slide_the_wave(self):
        """A real pause stands the media clock still while Genau's wave keeps
        moving in wall time, so every media-anchored forecast has slid off the
        wave it was cut from by the time the playhead moves again."""
        gate, session = _gate_holding_a_forecast()
        for _ in range(26):
            gate.readout(_stroke(), genau_behind=True)  # the playhead stands still

        session.position_ms = 40
        _a_newer_publish_arrives(gate)

        assert gate.handoff_touch() != CHOSEN_TOUCH_MS


class TestWhetherGenauHasBeenSeenLiveHere:
    """``let_go`` is Genau's own latch of the height it handed over at, and it
    survives a video change while Genau sits paused."""

    def test_a_handoff_from_before_this_video_is_read_as_still_live(self):
        """A descent drawn from that height tops a ramp the device never made
        here, so the publish is taken as though Genau still had the device."""
        gate = DriveGate(FakeSession())

        hud = gate.readout(_stroke(let_go=0.44), genau_behind=True)

        assert hud.let_go is None

    def test_once_genau_has_been_seen_live_a_handoff_is_honoured(self):
        gate = DriveGate(FakeSession())
        gate.readout(_stroke(), genau_behind=True)  # let_go unset: Genau has it

        hud = gate.readout(_stroke(let_go=0.44), genau_behind=True)

        assert hud.let_go == 0.44

    def test_a_new_video_makes_genau_prove_itself_live_again(self):
        session = FakeSession()
        gate = DriveGate(session)
        gate.readout(_stroke(), genau_behind=True)

        session.current_video = SECOND_VIDEO
        hud = gate.readout(_stroke(let_go=0.44), genau_behind=True)

        assert hud.let_go is None

    def test_a_stint_with_nobody_behind_the_screen_does_not_re_arm_it(self):
        """Leaving genau mode and coming back is not a new video: the device is
        where Genau left it, and the handoff it published still describes it."""
        gate = DriveGate(FakeSession())
        gate.readout(_stroke(), genau_behind=True)

        gate.readout(_stroke(), genau_behind=False)
        hud = gate.readout(_stroke(let_go=0.44), genau_behind=True)

        assert hud.let_go == 0.44
