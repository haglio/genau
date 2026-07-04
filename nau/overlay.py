"""On-screen state feedback for Nau: indicator and funscript heatmap strip.

The pure decision logic (which icon, the visible time window, strip
geometry) lives here untied to pygame so it is unit-testable; the drawing
helpers at the bottom turn those decisions into textures.
"""
from __future__ import annotations

import numpy as np

from .heatmap import build_heatmap


def indicator_for(loop_state: str, *, paused: bool) -> str:
    """Icon kind for the corner indicator: record/pause/loop/play.

    Recording trumps paused (the gesture is in progress); paused trumps
    looping (explains why nothing is moving).
    """
    if loop_state == "recording":
        return "record"
    if paused:
        return "pause"
    if loop_state == "looping":
        return "loop"
    return "play"


def record_available(*, has_funscript: bool) -> bool:
    """Whether loop recording (the R gesture) can do anything here.

    Unscripted videos have no funscript to loop against, so R is inert; the
    UI shows a muted "no fs" badge to explain the silence.
    """
    return has_funscript


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




def time_to_x(ms: float, start_ms: float, end_ms: float, width: int) -> int:
    """Strip x for a timestamp: its fraction of [start_ms, end_ms], kept on-strip."""
    span = end_ms - start_ms
    if span <= 0:
        return 0
    return max(0, min(width - 1, int((ms - start_ms) / span * width)))


# --- RGBA overlay rendering (BGRA arrays for mpv overlay_add) -----------------
# mpv owns the window and hardware-decodes the video; Nau's overlays go on top
# as BGRA bitmaps.  No pygame — these produce plain numpy arrays.

_ICON_BOX = 26
_ICON_MARGIN = 8
_WHITE = (230, 230, 230, 235)
_RED = (220, 40, 40, 245)
_AMBER = (235, 180, 60, 245)
_HEATMAP_ALPHA = 178  # ~70%: present but unobtrusive under the video
_BOUND_MARK_W = 3     # loop in/out and record in-point marks read as bars
_BADGE_MUTED = (150, 150, 150)


def _rgba_to_bgra(rgba):
    """(H, W, 4) RGBA uint8 -> BGRA (mpv's overlay format), contiguous."""
    bgra = rgba[:, :, [2, 1, 0, 3]]
    return np.ascontiguousarray(bgra, dtype=np.uint8)


def heatmap_bgra(heatmap, position_ms, loop_bounds, width):
    """The bottom heatmap strip as a BGRA array, or None when there is nothing
    to draw.  Includes the white playcursor, amber loop in/out marks, and the
    red record-in mark."""
    strip_h = heatmap.height
    if strip_h <= 0 or not heatmap.colors:
        return None
    row = np.asarray(heatmap.colors, dtype=np.uint8)  # (W, 3) RGB
    w = len(row)
    bgra = np.empty((strip_h, w, 4), dtype=np.uint8)
    bgra[:, :, 0] = row[np.newaxis, :, 2]
    bgra[:, :, 1] = row[np.newaxis, :, 1]
    bgra[:, :, 2] = row[np.newaxis, :, 0]
    bgra[:, :, 3] = _HEATMAP_ALPHA

    start_ms, end_ms = heatmap.window

    def mark(x, mark_w, color):
        x0 = max(0, x - mark_w // 2)
        x1 = min(w, x0 + mark_w)
        bgra[:, x0:x1, 0] = color[2]
        bgra[:, x0:x1, 1] = color[1]
        bgra[:, x0:x1, 2] = color[0]
        bgra[:, x0:x1, 3] = 255

    if heatmap.record_in_ms is not None:
        mark(time_to_x(heatmap.record_in_ms, start_ms, end_ms, w), _BOUND_MARK_W, _RED)
    if loop_bounds is not None:
        mark(time_to_x(loop_bounds[0], start_ms, end_ms, w), _BOUND_MARK_W, _AMBER)
        mark(time_to_x(loop_bounds[1], start_ms, end_ms, w), _BOUND_MARK_W, _AMBER)
    mark(time_to_x(position_ms, start_ms, end_ms, w), 1, _WHITE)
    return bgra


def indicator_bgra(kind: str):
    """The corner state icon (play/pause/record/loop) as a BGRA array."""
    import math

    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (_ICON_BOX, _ICON_BOX), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = cy = _ICON_BOX // 2
    d.ellipse([0, 0, _ICON_BOX - 1, _ICON_BOX - 1], fill=(0, 0, 0, 120))
    if kind == "play":
        d.polygon([(10, 7), (10, 19), (20, 13)], fill=_WHITE)
    elif kind == "pause":
        d.rectangle([8, 7, 11, 18], fill=_WHITE)
        d.rectangle([15, 7, 18, 18], fill=_WHITE)
    elif kind == "record":
        d.ellipse([cx - 7, cy - 7, cx + 7, cy + 7], fill=_RED)
    elif kind == "loop":
        r = 8
        d.arc([cx - r, cy - r, cx + r, cy + r], start=200, end=110, fill=_AMBER, width=2)
        d.polygon([(cx + r - 4, cy + 2), (cx + r + 3, cy + 2), (cx + r - 1, cy + 8)], fill=_AMBER)
    return _rgba_to_bgra(np.asarray(img))


def badge_bgra():
    """A muted "no fs" chip explaining why R is inert on unscripted videos."""
    from PIL import Image, ImageDraw

    text = "no fs"
    pad = 4
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    box = tmp.textbbox((0, 0), text)
    tw, th = box[2] - box[0], box[3] - box[1]
    img = Image.new("RGBA", (tw + pad * 2, th + pad * 3), (0, 0, 0, 120))
    ImageDraw.Draw(img).text((pad, pad), text, fill=_BADGE_MUTED)
    return _rgba_to_bgra(np.asarray(img))


def indicator_xy(win_w: int) -> tuple[int, int]:
    """Top-right anchor for the corner indicator."""
    return win_w - _ICON_BOX - _ICON_MARGIN, _ICON_MARGIN


def badge_xy(win_w: int, badge_w: int) -> tuple[int, int]:
    """Anchor for the no-fs chip, just left of the indicator."""
    return win_w - _ICON_BOX - _ICON_MARGIN - badge_w - 6, _ICON_MARGIN + 4
