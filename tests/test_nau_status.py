from __future__ import annotations

from pathlib import Path

from player_core.funscript import Funscript

from nau.descent_latch import DescentChoice, DescentLatch, DriveKey
from nau.status import next_handoff_touch, status_fields


class StubSession:
    def __init__(self) -> None:
        self.current_video = Path("C:/vids/clip.mp4")
        self.position_ms = 12345.6
        self.duration_ms = 60000.0
        self.has_funscript = True
        self.funscript_resting = False
        self.loop_state = "normal"
        self.loop_bounds = None
        self.is_paused = False
        self.locked = True


class TestStatusFields:
    def test_publishes_every_key_fun_time_reads(self):
        fields = status_fields(StubSession(), None)

        assert fields["video"] in ("C:\\vids\\clip.mp4", "C:/vids/clip.mp4")
        assert fields["position_ms"] == "12345"
        assert fields["duration_ms"] == "60000"
        assert fields["has_funscript"] == "1"
        assert fields["funscript_resting"] == "0"
        assert fields["state"] == "normal"
        assert fields["paused"] == "0"
        assert fields["locked"] == "1"

    def test_key_order_is_the_published_file_order(self):
        # fun_time parses key=value lines, but the file's shape is Nau's
        # contract; pinning the order keeps a reordering from passing silently.
        # Eleven, not ten: handoff_touch_ms is read by fun_time's dashboard
        # runtime and its dispatch loop, and while it was composed in a closure
        # inside nau.app's run loop this list said ten and nothing noticed.
        assert list(status_fields(StubSession(), None)) == [
            "video", "position_ms", "duration_ms",
            "has_funscript", "funscript_resting", "state",
            "loop_in_ms", "loop_out_ms", "paused", "locked",
            "handoff_touch_ms",
        ]

    def test_the_chosen_touch_is_published_as_whole_milliseconds(self):
        assert status_fields(StubSession(), 4200.7)["handoff_touch_ms"] == "4200"

    def test_no_chosen_touch_publishes_an_empty_field_rather_than_a_zero(self):
        """Zero is a real media time; an arbiter reading one would end Genau's
        turn at the top of the video."""
        assert status_fields(StubSession(), None)["handoff_touch_ms"] == ""

    def test_nothing_else_moves_when_the_touch_does(self):
        with_touch = status_fields(StubSession(), 4200)
        without = status_fields(StubSession(), None)

        assert {k: v for k, v in with_touch.items() if k != "handoff_touch_ms"} == {
            k: v for k, v in without.items() if k != "handoff_touch_ms"}

    def test_a_running_loop_publishes_the_range_it_holds(self):
        """The loop is the one thing on this player that a restart cannot
        rebuild from the playlist: it is a range inside one video, so the
        orchestrator can only hand it back if it is told what it was."""
        session = StubSession()
        session.loop_state = "looping"
        session.loop_bounds = (2000, 4000)

        fields = status_fields(session, None)

        assert (fields["loop_in_ms"], fields["loop_out_ms"]) == ("2000", "4000")

    def test_no_loop_publishes_an_empty_range(self):
        """Zeros rather than blanks, so the reader parses one shape either way —
        and an empty range is no loop, which is what it means."""
        fields = status_fields(StubSession(), None)

        assert (fields["loop_in_ms"], fields["loop_out_ms"]) == ("0", "0")

    def test_flags_follow_the_session(self):
        session = StubSession()
        session.has_funscript = False
        session.funscript_resting = True
        session.is_paused = True
        session.loop_state = "recording"
        session.locked = False

        fields = status_fields(session, None)

        assert fields["has_funscript"] == "0"
        assert fields["funscript_resting"] == "1"
        assert fields["paused"] == "1"
        assert fields["state"] == "recording"
        assert fields["locked"] == "0"

    def test_playhead_is_truncated_to_whole_milliseconds(self):
        session = StubSession()
        session.position_ms = 12345.9

        assert status_fields(session, None)["position_ms"] == "12345"


class TestTheTouchTheTraceChose:
    """``next_handoff_touch`` reads the choice out of the trace's own latch.

    One chooser, the picture, and the arbiter follows it: when each side chose
    its own touch from its own read of the wave they could pick different
    troughs, the arbiter stopped the device one touch early, and the leftover
    drawn blue vanished the moment the dot reached it.
    """

    # The boundary the script below opens its cluster at, and a touch latched
    # for it.
    BOUNDARY_MS = 3_000
    TOUCHING = DriveKey(center=50, amplitude=100, speed=50, let_go=None)

    @classmethod
    def _latched(cls, top: float = 0.35, touch: int | None = 3_600,
                 key: DriveKey | None = None) -> DescentLatch:
        latch = DescentLatch()
        latch.remember(cls.BOUNDARY_MS,
                       DescentChoice(key=key or cls.TOUCHING, top=top, touch=touch),
                       stale_before=0)
        return latch

    @staticmethod
    def _script() -> Funscript:
        return Funscript(actions=[(t, 0 if (t // 200) % 2 else 100)
                                  for t in range(8_000, 9_001, 200)])

    def test_an_unscripted_video_has_no_handoff_to_chose_one_for(self):
        assert next_handoff_touch(None, 0, self._latched()) is None

    def test_resting_before_a_turn_takes_the_turn_it_is_approaching(self):
        """The boundary in play is the one ahead: the device is about to change
        hands there."""
        assert next_handoff_touch(self._script(), 0, self._latched()) == 3_600

    def test_inside_a_turn_it_takes_the_boundary_just_crossed(self):
        """The arbiter is still ending that turn, so the touch it needs is the
        one the picture drew the ending on."""
        assert next_handoff_touch(self._script(), 5_000, self._latched()) == 3_600

    def test_a_rest_with_no_turn_after_it_has_no_boundary_at_all(self):
        """Past the last cluster nothing hands over again, and a lookup there
        would otherwise land on whatever the latch still held."""
        assert next_handoff_touch(self._script(), 20_000, self._latched()) is None

    def test_a_boundary_with_nothing_latched_yet_says_so(self):
        """The choice stays live while the boundary is far, so early in an
        approach there is nothing to publish."""
        assert next_handoff_touch(self._script(), 0, DescentLatch()) is None

    def test_a_ramped_handoff_has_no_touch_down_to_name(self):
        """A stroke whose floor sits above the park never comes down onto it:
        the grey ramps instead, and there is no touch."""
        ramped = self._latched(
            top=0.12, touch=None,
            key=DriveKey(center=50, amplitude=80, speed=50, let_go=None))

        assert next_handoff_touch(self._script(), 0, ramped) is None
