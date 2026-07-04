"""VideoStream decode/end-of-content behavior.

Covers the case where a container's reported duration (frame_count / fps)
overshoots the last frame the decoder can actually produce — common with
VFR or overstated frame counts. Seeking into that phantom tail must be
detected as end-of-content so playback advances instead of freezing.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from nau import playback
from nau.playback import VideoStream


class FakeCapture:
    """A cv2.VideoCapture stand-in with a phantom tail.

    Reports ``duration = frame_count / fps`` but ``read()`` returns
    ``(False, None)`` once the decode position reaches ``last_readable_ms``,
    modelling a file whose real content ends before its reported duration.
    """

    def __init__(self, *, fps: float, frame_count: float, last_readable_ms: float) -> None:
        self._fps = fps
        self._frame_count = frame_count
        self._last_readable_ms = last_readable_ms
        self._pos_ms = 0.0
        self.released = False

    def get(self, prop: int) -> float:
        if prop == playback.cv2.CAP_PROP_FPS:
            return self._fps
        if prop == playback.cv2.CAP_PROP_FRAME_COUNT:
            return self._frame_count
        if prop == playback.cv2.CAP_PROP_POS_MSEC:
            return self._pos_ms
        return 0.0

    def set(self, prop: int, value: float) -> bool:
        if prop == playback.cv2.CAP_PROP_POS_MSEC:
            self._pos_ms = value
        return True

    def read(self):
        if self._pos_ms >= self._last_readable_ms:
            return False, None
        frame = np.zeros((2, 2, 3), dtype=np.uint8)
        self._pos_ms += 1000.0 / self._fps
        return True, frame

    def release(self) -> None:
        self.released = True


def _open_stream(monkeypatch, *, fps=30.0, duration_ms=60_000.0, last_readable_ms=50_000.0):
    frame_count = duration_ms / 1000.0 * fps
    monkeypatch.setattr(
        playback.cv2, "VideoCapture",
        lambda _path: FakeCapture(fps=fps, frame_count=frame_count, last_readable_ms=last_readable_ms),
    )
    stream = VideoStream()
    stream.open(Path("fake.mp4"))
    return stream


class TestEndOfContent:
    def test_reports_container_duration(self, monkeypatch):
        stream = _open_stream(monkeypatch, duration_ms=60_000.0)
        assert stream.duration_ms == pytest.approx(60_000.0)

    def test_not_ended_mid_video(self, monkeypatch):
        stream = _open_stream(monkeypatch, last_readable_ms=50_000.0)
        stream.read_frame_at(40_000)
        assert not stream.ended

    def test_ended_when_decoder_eofs_before_reported_duration(self, monkeypatch):
        # The freeze bug: seeking into the phantom tail makes read() fail, the
        # frame goes stale, and last_frame_ms is stuck ~10s below duration — so
        # the old `last_frame_ms >= duration - 100` never fires.
        stream = _open_stream(monkeypatch, duration_ms=60_000.0, last_readable_ms=50_000.0)
        stream.read_frame_at(40_000)
        assert not stream.ended

        stream.read_frame_at(55_000)  # into the phantom tail → decoder EOF
        assert stream.ended

    def test_ended_clears_after_seeking_back_from_eof(self, monkeypatch):
        stream = _open_stream(monkeypatch, last_readable_ms=50_000.0)
        stream.read_frame_at(55_000)
        assert stream.ended

        stream.read_frame_at(30_000)  # seek back into readable content
        assert not stream.ended
