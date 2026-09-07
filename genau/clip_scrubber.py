"""The clip's playhead, drawn along the window's lower edge as Nau draws a video's.

A clip loops and there is no time in it to seek to, so this is a readout rather
than a control: where the Robot Hand has taken the loop, which is the one thing
about the clip the console cannot say.
"""
from __future__ import annotations

import numpy as np
from player_core.timeline import TIMELINE_HEIGHT, bar_track_x, progress_bar_bgra


class ClipScrubber:
    """What the bar shows, read off the renderer that is showing the frames.

    Built beside the console and the volume chip, so what is drawn is one object
    the app wires -- but told its renderer afterwards, because the renderer is
    built around the view and cannot be handed to it first.
    """

    def __init__(self) -> None:
        self._renderer = None

    def follow(self, renderer) -> None:
        self._renderer = renderer

    def playhead(self) -> tuple[int, int]:
        """How far through the clip the motion has taken it, of how far there is
        to go; (0, 0) before any clip is up.

        Counted UP, which the frame that is up is not: player_core shows a clip
        from its last frame back (clip_renderer.display_index_for_phase), so a
        cursor drawn straight off that index walked backwards along the bar.
        """
        if self._renderer is None:
            return (0, 0)
        entry = self._renderer.current_clip_entry()
        frames = entry.get("frames") if entry else None
        count = len(frames) if frames else 0
        index = self._renderer.current_frame_index
        return (0 if index is None else max(0, count - 1 - index), count)

    def bgra(self, width: int) -> np.ndarray | None:
        """The bar at this window width, or None while there is no clip to draw."""
        played, of = self.playhead()
        if of <= 0 or width <= 0:
            return None
        return progress_bar_bgra(played, of, None, width)

    def takes(self, my: int, *, win_h: int) -> bool:
        """Whether a press this far down the window is on the bar."""
        return self.playhead()[1] > 0 and my >= win_h - TIMELINE_HEIGHT

    @staticmethod
    def fraction_at(mx: int, *, win_w: int) -> float:
        """How far along the bar a press at *mx* is, saturating past either end."""
        x0, x1 = bar_track_x(win_w)
        return min(1.0, max(0.0, (mx - x0) / max(1, x1 - x0)))
