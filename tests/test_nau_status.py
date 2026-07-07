from __future__ import annotations

from pathlib import Path

from nau.status import StatusWriter


class StubSession:
    def __init__(self) -> None:
        self.current_video = Path("C:/vids/clip.mp4")
        self.position_ms = 12345.6
        self.duration_ms = 60000.0
        self.has_funscript = True
        self.funscript_resting = False
        self.loop_state = "normal"
        self.is_paused = False


class TestStatusWriter:
    def test_writes_all_fields(self, tmp_path):
        status_path = tmp_path / "nau_status.txt"
        clock = {"t": 0.0}
        writer = StatusWriter(status_path, now_source=lambda: clock["t"])
        session = StubSession()

        assert writer.write(session)

        text = status_path.read_text(encoding="utf-8")
        assert "video=C:\\vids\\clip.mp4\n" in text or "video=C:/vids/clip.mp4\n" in text
        assert "position_ms=12345\n" in text
        assert "duration_ms=60000\n" in text
        assert "has_funscript=1\n" in text
        assert "funscript_resting=0\n" in text
        assert "state=normal\n" in text
        assert "paused=0\n" in text

    def test_throttles_writes_within_interval(self, tmp_path):
        status_path = tmp_path / "nau_status.txt"
        clock = {"t": 0.0}
        writer = StatusWriter(status_path, min_interval=0.2, now_source=lambda: clock["t"])
        session = StubSession()

        writer.write(session)
        session.position_ms = 12400.0
        clock["t"] = 0.1

        assert not writer.write(session)
        assert "position_ms=12345" in status_path.read_text(encoding="utf-8")

    def test_writes_again_after_interval(self, tmp_path):
        status_path = tmp_path / "nau_status.txt"
        clock = {"t": 0.0}
        writer = StatusWriter(status_path, min_interval=0.2, now_source=lambda: clock["t"])
        session = StubSession()

        writer.write(session)
        session.position_ms = 12400.0
        session.loop_state = "recording"
        clock["t"] = 0.25

        assert writer.write(session)
        text = status_path.read_text(encoding="utf-8")
        assert "position_ms=12400" in text
        assert "state=recording" in text
