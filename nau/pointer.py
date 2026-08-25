"""Where a press on Nau's window lands, once the console has had its turn.

Three zones, all measured up from the bottom edge: the volume chip at the
right-hand end of the timeline row, the rest of that row, and the video above
it.  The console's own buttons are hit-tested before any of this — they are the
shared HUD's, and a press they take never reaches here.

Lived as a closure inside ``nau.app``'s run loop, so the one thing this decides
— whether a press seeks or pauses — could only be exercised by opening a window
and clicking in it.  Inverting the test, so a click on the video seeked and a
click on the timeline paused, left the whole suite green.
"""
from __future__ import annotations

from .overlay import bar_track_x, timeline_height


class Pointer:
    """The video under the pointer, and what a press or a drag on it does."""

    def __init__(self, session, heatmap, volume) -> None:
        self._session = session
        self._heatmap = heatmap
        self._volume = volume

    def press(self, mx: int, my: int, *, win_w: int, win_h: int) -> None:
        """Take a press at window ``(mx, my)``."""
        row_h = timeline_height(self._heatmap)
        # The volume chip first — it floats over the video, so a press on it is
        # never also a press on what is behind it.
        if self._volume.press_at(mx, my, win_w=win_w, win_h=win_h, timeline_h=row_h):
            return
        if my >= win_h - row_h:
            self._session.seek_to(self._time_at(mx, win_w))
        else:
            self._session.toggle_pause()

    def drag(self, mx: int, my: int, *, win_w: int, win_h: int) -> None:
        """Take a drag at window ``(mx, my)`` with the button still held.

        Only the volume slider answers one; dragging across the video is how a
        pointer crosses the window, not a control being moved.
        """
        self._volume.drag_at(mx, my, win_w=win_w, win_h=win_h,
                             timeline_h=timeline_height(self._heatmap))

    def _time_at(self, mx: int, win_w: int) -> float:
        """The media time the timeline puts under *mx*.

        The strip maps whatever window it is currently showing — the whole video
        normally, and while a loop is being recorded the zoomed section around
        the in point — so the press and the picture agree.  Before the first
        strip is built there is no window yet and the video's own length is the
        map instead.

        Both the heatmap strip and the plain bar are inset to the same track, so
        a press maps onto it the same way; past either end it saturates, which
        is what a pointer dragged off the end is asking for.
        """
        start_ms, end_ms = self._heatmap.window
        if end_ms <= start_ms:
            end_ms = start_ms + self._session.duration_ms
        x0, x1 = bar_track_x(win_w)
        frac = min(1.0, max(0.0, (mx - x0) / max(1, x1 - x0)))
        return start_ms + frac * (end_ms - start_ms)
