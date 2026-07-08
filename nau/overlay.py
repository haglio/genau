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
# as BGRA bitmaps.  No pygame — these produce plain numpy arrays.

_ICON_BOX = 26
_ICON_MARGIN = 8
_WHITE = (230, 230, 230, 235)
_RED = (220, 40, 40, 245)
_AMBER = (235, 180, 60, 245)
_HEATMAP_ALPHA = 178  # ~70%: present but unobtrusive under the video

# The timeline — heatmap strip or plain bar — is drawn as one shared frame: an
# inset, floated, bordered track with full-height marks.
_BAR_INSET_X = 40     # side margin so the timeline's start/end clear the edges
_BAR_INSET_Y = 3      # top/bottom margin so the timeline floats off the edge
_BAR_FILL = (34, 34, 38, 165)       # dark translucent fill (plain bar only)
_BAR_BORDER = (215, 215, 220, 235)  # light inner border (reads on the dark fill)
_BAR_EDGE = (8, 8, 10, 235)         # dark outer edge (reads on the bright heatmap)
_BORDER_W = 2
_CURSOR = (255, 255, 255, 255)   # prominent white playcursor
_CURSOR_W = 3
_MARK_W = 4                      # prominent loop in/out and record marks


TIMELINE_HEIGHT = _IDLE_HEIGHT  # bottom strip height when not recording


def bar_track_x(width: int) -> tuple[int, int]:
    """Left/right pixel bounds of the inset timeline track, so its start and end
    sit a margin in from the window's side edges.  Clamped so the track never
    inverts on a very narrow window.  Both the heatmap strip and the plain bar
    use this, and click-to-seek maps onto it."""
    inset = min(_BAR_INSET_X, max(0, width // 2 - 1))
    return inset, width - inset


def _rgba_to_bgra(rgba):
    """(H, W, 4) RGBA uint8 -> BGRA (mpv's overlay format), contiguous."""
    bgra = rgba[:, :, [2, 1, 0, 3]]
    return np.ascontiguousarray(bgra, dtype=np.uint8)


def _paint_rect(bgra, x0, x1, y0, y1, color):
    """Fill rows [y0:y1], cols [x0:x1] with an RGBA ``color``, clamped to the
    array (stored BGRA for mpv)."""
    h, w = bgra.shape[:2]
    x0, x1 = max(0, x0), min(w, x1)
    y0, y1 = max(0, y0), min(h, y1)
    if x1 <= x0 or y1 <= y0:
        return
    bgra[y0:y1, x0:x1] = (color[2], color[1], color[0], color[3])


def _ring(bgra, x0, x1, y0, y1, t, color):
    """Draw a ``t``-thick hollow rectangle just inside [x0:x1] x [y0:y1]."""
    _paint_rect(bgra, x0, x1, y0, y0 + t, color)  # top
    _paint_rect(bgra, x0, x1, y1 - t, y1, color)  # bottom
    _paint_rect(bgra, x0, x0 + t, y0, y1, color)  # left
    _paint_rect(bgra, x1 - t, x1, y0, y1, color)  # right


def _draw_border(bgra, x0, x1, y0, y1, bw, color):
    """A two-tone frame: a 1px dark outer edge inside a light inner border, so
    it reads against both the plain bar's dark fill and the bright heatmap."""
    _ring(bgra, x0, x1, y0, y1, 1, _BAR_EDGE)
    _ring(bgra, x0 + 1, x1 - 1, y0 + 1, y1 - 1, bw - 1, color)


def _paint_mark(bgra, x_center, mark_w, y0, y1, color, *, x_lo, x_hi):
    """Paint a ``mark_w``-wide vertical bar centred on ``x_center``, kept
    within [x_lo, x_hi]."""
    left = max(x_lo, x_center - mark_w // 2)
    right = min(x_hi, left + mark_w)
    _paint_rect(bgra, left, right, y0, y1, color)


def _bar_x(ms, duration_ms, x0, x1):
    """Track x for a timestamp: its fraction of the video, mapped into
    [x0, x1] and kept on-track."""
    frac = min(1.0, max(0.0, ms / max(1.0, duration_ms)))
    return x0 + int(frac * (x1 - x0 - 1))


def _framed_track(width, height):
    """A transparent full-width BGRA array plus the inset, floated track rect
    (x0, x1, y0, y1) that both the plain bar and the heatmap strip draw into."""
    bar = np.zeros((height, width, 4), dtype=np.uint8)
    x0, x1 = bar_track_x(width)
    return bar, x0, x1, _BAR_INSET_Y, height - _BAR_INSET_Y


def _draw_track_marks(bgra, *, x0, x1, y0, y1, to_x, position_ms,
                      loop_bounds, record_in_ms):
    """Full-height playcursor + amber loop in/out (and red record-in) ticks on a
    framed track.  ``to_x(ms)`` maps a timestamp to an absolute x in [x0, x1].
    Ticks span the whole frame (crossing the border) and are fully opaque, so
    they stay prominent over any fill or video."""
    def mark(ms, mark_w, color):
        _paint_mark(bgra, to_x(ms), mark_w, y0, y1, (*color[:3], 255),
                    x_lo=x0, x_hi=x1)

    if record_in_ms is not None:
        mark(record_in_ms, _MARK_W, _RED)
    if loop_bounds is not None:
        mark(loop_bounds[0], _MARK_W, _AMBER)
        mark(loop_bounds[1], _MARK_W, _AMBER)
    mark(position_ms, _CURSOR_W, _CURSOR)  # playcursor on top


def progress_bar_bgra(position_ms, duration_ms, loop_bounds, width,
                      record_in_ms=None, height=TIMELINE_HEIGHT):
    """A bordered, inset seek bar for videos with no funscript heatmap.

    Shares the heatmap strip's frame — a dark translucent track floated in from
    the window edges under a light border, with a full-height white playcursor
    and full-height loop in/out marks (amber; the in point shows red while it is
    still being recorded) — so every video, scripted or not, has a clear,
    clickable timeline.
    """
    bar, x0, x1, y0, y1 = _framed_track(width, height)
    _paint_rect(bar, x0, x1, y0, y1, _BAR_FILL)
    _draw_border(bar, x0, x1, y0, y1, _BORDER_W, _BAR_BORDER)
    _draw_track_marks(
        bar, x0=x0, x1=x1, y0=y0, y1=y1,
        to_x=lambda ms: _bar_x(ms, duration_ms, x0, x1),
        position_ms=position_ms, loop_bounds=loop_bounds, record_in_ms=record_in_ms,
    )
    return bar


def _text_chip(text: str, *, fg=(240, 240, 240)):
    """A translucent dark chip sized to *text*, for a screen corner."""
    from PIL import Image, ImageDraw

    pad = 5
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    box = tmp.textbbox((0, 0), text)
    tw, th = box[2] - box[0], box[3] - box[1]
    img = Image.new("RGBA", (tw + pad * 2, th + pad * 3), (0, 0, 0, 160))
    ImageDraw.Draw(img).text((pad, pad), text, fill=fg)
    return _rgba_to_bgra(np.asarray(img))


def name_bgra(text: str):
    """The current video's name as a translucent chip for the top-left."""
    return _text_chip(text)


def _format_speed(speed: float) -> str:
    """Playback rate as a compact label, e.g. 1.0 -> '1×', 1.5 -> '1.5×'."""
    return f"{speed:g}×"


def speed_bgra(speed: float):
    """The current playback rate as an amber chip (shown only when off 1×)."""
    return _text_chip(_format_speed(speed), fg=(255, 205, 90))


def heatmap_bgra(heatmap, position_ms, loop_bounds, width):
    """The bottom heatmap strip as a BGRA array, or None when there is nothing
    to draw.  Uses the same inset, floated, bordered frame and full-height marks
    as the plain bar, with the funscript heatmap as the track fill.  The colour
    row must have been built at the track width (``bar_track_x(width)``)."""
    strip_h = heatmap.height
    if strip_h <= 0 or not heatmap.colors:
        return None
    bar, x0, x1, y0, y1 = _framed_track(width, strip_h)
    row = np.asarray(heatmap.colors, dtype=np.uint8)  # (track_w, 3) RGB
    track_w = len(row)
    x1 = x0 + track_w  # the colour row defines the exact track width
    bar[y0:y1, x0:x1, 0] = row[np.newaxis, :, 2]
    bar[y0:y1, x0:x1, 1] = row[np.newaxis, :, 1]
    bar[y0:y1, x0:x1, 2] = row[np.newaxis, :, 0]
    bar[y0:y1, x0:x1, 3] = _HEATMAP_ALPHA
    _draw_border(bar, x0, x1, y0, y1, _BORDER_W, _BAR_BORDER)

    start_ms, end_ms = heatmap.window
    _draw_track_marks(
        bar, x0=x0, x1=x1, y0=y0, y1=y1,
        to_x=lambda ms: x0 + time_to_x(ms, start_ms, end_ms, track_w),
        position_ms=position_ms, loop_bounds=loop_bounds,
        record_in_ms=heatmap.record_in_ms,
    )
    return bar


def indicator_bgra(kind: str):
    """The corner state icon (play/pause/record/loop) as a BGRA array."""
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


def indicator_xy(win_w: int) -> tuple[int, int]:
    """Top-right anchor for the corner indicator."""
    return win_w - _ICON_BOX - _ICON_MARGIN, _ICON_MARGIN
