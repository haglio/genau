from __future__ import annotations

from pathlib import Path

from satellite.session import SatelliteSession
from satellite.status import StatusWriter
from satellite_fakes import FakeSatellitePlayer


class _Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def _make_session(tmp_path):
    vid = tmp_path / "clip.mp4"
    vid.write_text("fake")
    return SatelliteSession([vid], player=FakeSatellitePlayer())


def _read(path: Path) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )


class TestStatusWriter:
    def test_writes_the_session_state_as_key_value_lines(self, tmp_path):
        session = _make_session(tmp_path)
        session._player.position_ms = 1_500.0
        session.set_locked(True)
        writer = StatusWriter(tmp_path / "portrait_status.txt", now_source=_Clock())

        assert writer.write(session) is True
        fields = _read(tmp_path / "portrait_status.txt")
        assert fields["video"] == str(tmp_path / "clip.mp4")
        assert fields["position_ms"] == "1500"
        assert fields["duration_ms"] == "5000"
        assert fields["paused"] == "0"
        assert fields["locked"] == "1"

    def test_throttles_writes_within_the_min_interval(self, tmp_path):
        session = _make_session(tmp_path)
        clock = _Clock()
        writer = StatusWriter(tmp_path / "s.txt", min_interval=0.2, now_source=clock)

        assert writer.write(session) is True
        clock.t += 0.1  # still inside the interval
        assert writer.write(session) is False

    def test_writes_again_after_the_interval_elapses(self, tmp_path):
        session = _make_session(tmp_path)
        clock = _Clock()
        writer = StatusWriter(tmp_path / "s.txt", min_interval=0.2, now_source=clock)

        assert writer.write(session) is True
        clock.t += 0.3
        assert writer.write(session) is True
