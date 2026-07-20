"""On-screen state feedback for Nau: the funscript heatmap strip and timeline.

The pure decision logic (the visible time window, strip geometry) lives here
untied to pygame so it is unit-testable; the drawing helpers at the bottom turn
those decisions into textures.
"""
from __future__ import annotations

import numpy as np

# The scrubber and its frame are the shared engine's now, so every player draws
# the same one; the funscript heatmap below is Nau's own, built on that frame.
# bar_track_x and progress_bar_bgra are re-exported for nau.app, which draws them.
from player_core.timeline import (  # noqa: F401 (bar_track_x/progress_bar_bgra re-exported)
    BAR_BORDER,
    BORDER_W,
    TIMELINE_HEIGHT,
    bar_track_x,
    draw_border,
    draw_track_marks,
    framed_track,
    progress_bar_bgra,
    rgba_to_bgra,
)

from .heatmap import build_heatmap

_ZOOM_SPAN_START_MS = 20_000.0
_ZOOM_LEAD_FRAC = 0.10
_ZOOM_GROW_FRAC = 0.85


class ZoomWindow:
    """Stepped time window for the recording zoom.

    Shows [in - lead, in + span] with a 10% lead so the in point sits just
    inside the left edge; span starts at 20s and doubles whenever the
    playhead passes 85% of the window, so the view rescales in steps
    rather than sliding continuously.
    """

    def __init__(self, *, in_ms: float) -> None:
        self._in_ms = in_ms
        self._span = _ZOOM_SPAN_START_MS

    @property
    def in_ms(self) -> float:
        return self._in_ms

    @property
    def bounds(self) -> tuple[float, float]:
        return self._in_ms - self._span * _ZOOM_LEAD_FRAC, self._in_ms + self._span

    def update(self, position_ms: float) -> None:
        while position_ms > self._grow_at():
            self._span *= 2

    def _grow_at(self) -> float:
        start, end = self.bounds
        return start + (end - start) * _ZOOM_GROW_FRAC


_IDLE_HEIGHT = 24
_RECORDING_HEIGHT = 48


class HeatmapStrip:
    """Funscript heatmap pinned to the window's bottom edge.

    Normally a full-duration view; while a loop is being recorded it
    becomes a taller strip zoomed into the section around the in point
    (a stepped ZoomWindow), so the user can judge where to end the loop.
    The color row is expensive to build (one bucket per pixel), so
    update() rebuilds only when the video, the width, or the visible
    time window changes.
    """

    def __init__(self) -> None:
        self._key: tuple | None = None
        self._colors: list[tuple[int, int, int]] = []
        self._duration_ms = 0.0
        self._zoom: ZoomWindow | None = None

    @property
    def colors(self) -> list[tuple[int, int, int]]:
        return self._colors

    @property
    def height(self) -> int:
        """Strip height in px — 0 when there is nothing to draw."""
        if not self._colors:
            return 0
        return _RECORDING_HEIGHT if self._zoom is not None else _IDLE_HEIGHT

    @property
    def window(self) -> tuple[float, float]:
        """Visible time range (start_ms, end_ms) the strip currently maps."""
        if self._zoom is not None:
            return self._zoom.bounds
        return 0.0, self._duration_ms

    @property
    def record_in_ms(self) -> float | None:
        """In point of the recording being zoomed — None outside recording."""
        return self._zoom.in_ms if self._zoom is not None else None

    def update(
        self,
        video_key,
        funscript,
        duration_ms: float,
        width: int,
        *,
        loop_state: str = "normal",
        record_in_ms: float | None = None,
        position_ms: float = 0.0,
    ) -> None:
        if loop_state == "recording" and funscript is not None:
            if self._zoom is None:
                self._zoom = ZoomWindow(in_ms=record_in_ms)
            self._zoom.update(position_ms)
        else:
            self._zoom = None
        self._duration_ms = duration_ms
        key = (video_key, width, self.window)
        if key == self._key:
            return
        self._key = key
        if funscript is None:
            self._colors = []
        else:
            start, end = self.window
            self._colors = build_heatmap(
                funscript, max(1, width), start_ms=start, end_ms=end,
            )




_THUMB_H = 64
_OUT_CAPTURE_LEAD_MS = 400.0


class LoopThumbCapture:
    """Decides when to grab the loop's in/out frame thumbnails.

    The frames come from mpv screenshots (the caller does the actual grab),
    so this only owns the *when*: the in frame once the loop starts, the out
    frame once playback nears the out point.  Cleared when the loop changes
    or ends.  ``in_thumb`` / ``out_thumb`` hold the grabbed BGRA arrays.
    """

    def __init__(self) -> None:
        self._bounds: tuple[int, int] | None = None
        self.in_thumb = None
        self.out_thumb = None

    def needed(self, loop_state: str, loop_bounds, position_ms: float) -> str | None:
        if loop_state != "looping" or loop_bounds is None:
            self._bounds = None
            self.in_thumb = None
            self.out_thumb = None
            return None
        if loop_bounds != self._bounds:
            self._bounds = loop_bounds
            self.in_thumb = None
            self.out_thumb = None
        if self.in_thumb is None:
            return "in"
        if self.out_thumb is None and position_ms >= loop_bounds[1] - _OUT_CAPTURE_LEAD_MS:
            return "out"
        return None

    def set(self, which: str, thumb) -> None:
        if which == "in":
            self.in_thumb = thumb
        elif which == "out":
            self.out_thumb = thumb


def label_xs(in_x: int, out_x: int, in_w: int, out_w: int, win_w: int) -> tuple[int, int]:
    """Left edges for the in/out thumbnail labels: centered on their markers,
    clamped on-screen, and the out label nudged right of the in label when
    they would overlap."""
    ix = max(0, min(win_w - in_w, in_x - in_w // 2))
    ox = max(0, min(win_w - out_w, out_x - out_w // 2))
    if ox < ix + in_w:
        ox = min(win_w - out_w, ix + in_w + 2)
    return ix, ox


def time_to_x(ms: float, start_ms: float, end_ms: float, width: int) -> int:
    """Strip x for a timestamp: its fraction of [start_ms, end_ms], kept on-strip."""
    span = end_ms - start_ms
    if span <= 0:
        return 0
    return max(0, min(width - 1, int((ms - start_ms) / span * width)))


# --- RGBA overlay rendering (BGRA arrays for mpv overlay_add) -----------------
# mpv owns the window and hardware-decodes the video; Nau's overlays go on top
# as BGRA bitmaps.  No pygame — these produce plain numpy arrays.  The scrubber
# and its frame come from player_core.timeline; the heatmap fill below is Nau's.

_HEATMAP_ALPHA = 178  # ~70%: present but unobtrusive under the video


def _text_chip(text: str, *, fg=(240, 240, 240)):
    """A translucent dark chip sized to *text*, for a screen corner."""
    from PIL import Image, ImageDraw

    pad = 5
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    box = tmp.textbbox((0, 0), text)
    tw, th = box[2] - box[0], box[3] - box[1]
    img = Image.new("RGBA", (tw + pad * 2, th + pad * 3), (0, 0, 0, 160))
    ImageDraw.Draw(img).text((pad, pad), text, fill=fg)
    return rgba_to_bgra(np.asarray(img))


def name_bgra(text: str):
    """The current video's name as a translucent chip for the top-left."""
    return _text_chip(text)


def heatmap_bgra(heatmap, position_ms, loop_bounds, width):
    """The bottom heatmap strip as a BGRA array, or None when there is nothing
    to draw.  Uses the same inset, floated, bordered frame and full-height marks
    as the plain bar, with the funscript heatmap as the track fill.  The colour
    row must have been built at the track width (``bar_track_x(width)``)."""
    strip_h = heatmap.height
    if strip_h <= 0 or not heatmap.colors:
        return None
    bar, x0, x1, y0, y1 = framed_track(width, strip_h)
    row = np.asarray(heatmap.colors, dtype=np.uint8)  # (track_w, 3) RGB
    track_w = len(row)
    x1 = x0 + track_w  # the colour row defines the exact track width
    bar[y0:y1, x0:x1, 0] = row[np.newaxis, :, 2]
    bar[y0:y1, x0:x1, 1] = row[np.newaxis, :, 1]
    bar[y0:y1, x0:x1, 2] = row[np.newaxis, :, 0]
    bar[y0:y1, x0:x1, 3] = _HEATMAP_ALPHA
    draw_border(bar, x0, x1, y0, y1, BORDER_W, BAR_BORDER)

    start_ms, end_ms = heatmap.window
    draw_track_marks(
        bar, x0=x0, x1=x1, y0=y0, y1=y1,
        to_x=lambda ms: x0 + time_to_x(ms, start_ms, end_ms, track_w),
        position_ms=position_ms, loop_bounds=loop_bounds,
        record_in_ms=heatmap.record_in_ms,
    )
    return bar


