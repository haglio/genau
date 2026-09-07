"""The clip's playhead, drawn along the window's lower edge as Nau draws a video's.

A clip loops and there is no time in it to seek to, so this is a readout rather
than a control: where the Robot Hand has taken the loop, which is the one thing
about the clip the console cannot say.
"""
from __future__ import annotations

import numpy as np
from player_core.timeline import progress_bar_bgra


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
        """Which frame is on screen, of how many; (0, 0) before any clip is."""
        if self._renderer is None:
            return (0, 0)
        entry = self._renderer.current_clip_entry()
        frames = entry.get("frames") if entry else None
        index = self._renderer.current_frame_index
        return (0 if index is None else index, len(frames) if frames else 0)

    def bgra(self, width: int) -> np.ndarray | None:
        """The bar at this window width, or None while there is no clip to draw."""
        played, of = self.playhead()
        if of <= 0 or width <= 0:
            return None
        return progress_bar_bgra(played, of, None, width)
