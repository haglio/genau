"""What Nau's own module does, above the parts it composes.

``nau.app`` is imported inside each test rather than at module scope: importing
it pulls pygame in for real, and the view tests that replace pygame with a mock
go red inside pygame's own resource lookup if that happens before they run.
By the time these do, those have.  ``tests/test_taskbar_identity.py`` reaches
its two names the same way and says the same thing.
"""
from __future__ import annotations

import numpy as np

from nau.overlay import HeatmapStrip, LoopThumbCapture
from player_core.funscript import Funscript

WIN_W, WIN_H = 1000, 600
LOOP = (2000, 4000)


class FakePlayer:
    """mpv's side of the overlay calls: what was drawn where, and what was
    taken off the screen again."""

    def __init__(self, frame=None) -> None:
        self.drawn: dict[int, tuple[int, int, object]] = {}
        self.removed: list[int] = []
        self._frame = frame

    def screenshot_bgra(self):
        return self._frame

    def overlay(self, ident: int, x: int, y: int, thumb) -> None:
        self.drawn[ident] = (x, y, thumb)

    def remove_overlay(self, ident: int) -> None:
        self.removed.append(ident)


class FakeSession:
    def __init__(self, *, bounds=LOOP, position_ms: float = 2000.0) -> None:
        self.loop_bounds = bounds
        self.loop_state = "looping" if bounds is not None else "normal"
        self.position_ms = position_ms


def _frame(height: int = 10, width: int = 20):
    return np.zeros((height, width, 4), dtype=np.uint8)


def _strip() -> HeatmapStrip:
    strip = HeatmapStrip()
    strip.update("v0.mp4", Funscript(actions=[(0, 0), (1000, 100), (2000, 0)]),
                 4000.0, width=40)
    return strip


def _draw(player, thumbs, session, heatmap) -> None:
    from nau.app import _draw_loop_thumbnails
    _draw_loop_thumbnails(player, thumbs, session, heatmap, WIN_W, WIN_H)


def _ids() -> tuple[int, int]:
    from nau.app import _OV_IN_THUMB, _OV_OUT_THUMB
    return _OV_IN_THUMB, _OV_OUT_THUMB


class TestTheLoopsOwnTwoFrames:
    """A running loop shows the frame it starts on and the frame it ends on,
    above their marks on the timeline.  The frames come from mpv screenshots,
    which is why the capture is asked for one at a time: the in frame when the
    loop opens, the out frame only as playback nears the out point.
    """

    def test_the_first_frame_is_grabbed_and_drawn_when_the_loop_opens(self):
        in_thumb, _out = _ids()
        player = FakePlayer(_frame())
        thumbs = LoopThumbCapture()

        _draw(player, thumbs, FakeSession(), _strip())

        assert thumbs.in_thumb is player.drawn[in_thumb][2]

    def test_the_last_frame_joins_it_as_the_loop_comes_round(self):
        in_thumb, out_thumb = _ids()
        player = FakePlayer(_frame())
        thumbs = LoopThumbCapture()
        session = FakeSession()
        heatmap = _strip()

        _draw(player, thumbs, session, heatmap)
        session.position_ms = 3700.0        # inside the out frame's lead
        _draw(player, thumbs, session, heatmap)

        assert set(player.drawn) == {in_thumb, out_thumb}

    def test_a_frame_not_grabbed_yet_is_not_drawn(self):
        """mpv answers None while it has no picture to give -- between videos,
        or before the first frame has been decoded."""
        in_thumb, out_thumb = _ids()
        player = FakePlayer(None)

        _draw(player, LoopThumbCapture(), FakeSession(), _strip())

        assert (in_thumb in player.drawn, out_thumb in player.drawn) == (False, False)

    def test_the_end_of_a_loop_takes_both_frames_off_the_screen(self):
        """Overlay ids are stable so each frame updates in place, which is also
        why they have to be removed by hand: left alone, the thumbnails of a
        cancelled loop stay over the video for the rest of the session."""
        in_thumb, out_thumb = _ids()
        player = FakePlayer(_frame())
        thumbs = LoopThumbCapture()
        heatmap = _strip()
        _draw(player, thumbs, FakeSession(), heatmap)

        _draw(player, thumbs, FakeSession(bounds=None), heatmap)

        assert player.removed == [in_thumb, out_thumb]
