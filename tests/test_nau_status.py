from __future__ import annotations

from pathlib import Path

from nau.status import status_fields


class StubSession:
    def __init__(self) -> None:
        self.current_video = Path("C:/vids/clip.mp4")
        self.position_ms = 12345.6
        self.duration_ms = 60000.0
        self.has_funscript = True
        self.funscript_resting = False
        self.loop_state = "normal"
        self.is_paused = False
        self.locked = True


class TestStatusFields:
    def test_publishes_every_key_fun_time_reads(self):
        fields = status_fields(StubSession())

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
        assert list(status_fields(StubSession())) == [
            "video", "position_ms", "duration_ms",
            "has_funscript", "funscript_resting", "state", "paused", "locked",
        ]

    def test_flags_follow_the_session(self):
        session = StubSession()
        session.has_funscript = False
        session.funscript_resting = True
        session.is_paused = True
        session.loop_state = "recording"
        session.locked = False

        fields = status_fields(session)

        assert fields["has_funscript"] == "0"
        assert fields["funscript_resting"] == "1"
        assert fields["paused"] == "1"
        assert fields["state"] == "recording"
        assert fields["locked"] == "0"

    def test_playhead_is_truncated_to_whole_milliseconds(self):
        session = StubSession()
        session.position_ms = 12345.9

        assert status_fields(session)["position_ms"] == "12345"
