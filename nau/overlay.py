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


def time_to_x(ms: float, start_ms: float, end_ms: float, width: int) -> int:
    """Strip x for a timestamp: its fraction of [start_ms, end_ms], kept on-strip."""
    span = end_ms - start_ms
    if span <= 0:
        return 0
    return max(0, min(width - 1, int((ms - start_ms) / span * width)))


# --- pygame drawing (thin; no decision logic below this line) ---------------

_ICON_BOX = 26
_ICON_MARGIN = 8
_WHITE = (230, 230, 230, 220)
_RED = (220, 40, 40, 235)
_AMBER = (235, 180, 60, 230)


def _icon_surface(kind: str):
    import math

    import pygame

    s = pygame.Surface((_ICON_BOX, _ICON_BOX), pygame.SRCALPHA)
    cx = cy = _ICON_BOX // 2
    pygame.draw.circle(s, (0, 0, 0, 120), (cx, cy), _ICON_BOX // 2)
    if kind == "play":
        pygame.draw.polygon(s, _WHITE, [(10, 7), (10, 19), (20, 13)])
    elif kind == "pause":
        pygame.draw.rect(s, _WHITE, pygame.Rect(8, 7, 4, 12))
        pygame.draw.rect(s, _WHITE, pygame.Rect(15, 7, 4, 12))
    elif kind == "record":
        pygame.draw.circle(s, _RED, (cx, cy), 7)
    elif kind == "loop":
        r = 8
        rect = pygame.Rect(cx - r, cy - r, r * 2, r * 2)
        pygame.draw.arc(s, _AMBER, rect, 0.5, 2.0 * math.pi - 0.9, 2)
        pygame.draw.polygon(
            s, _AMBER, [(cx + r - 4, cy + 2), (cx + r + 3, cy + 2), (cx + r - 1, cy + 8)]
        )
    return s


def draw_indicator(renderer, kind: str, win_w: int) -> None:
    import pygame
    from pygame._sdl2.video import Texture

    surface = _icon_surface(kind)
    texture = Texture.from_surface(renderer, surface)
    texture.draw(
        dstrect=pygame.Rect(win_w - _ICON_BOX - _ICON_MARGIN, _ICON_MARGIN, _ICON_BOX, _ICON_BOX)
    )


_HEATMAP_ALPHA = 178  # ~70%: present but unobtrusive under the video
_BOUND_MARK_W = 3  # loop in/out and record in-point marks read as bars


def _draw_mark(renderer, x: int, width: int, strip_h: int, win_h: int, color) -> None:
    import pygame
    from pygame._sdl2.video import Texture

    mark = pygame.Surface((width, strip_h), pygame.SRCALPHA)
    mark.fill(color)
    Texture.from_surface(renderer, mark).draw(
        dstrect=pygame.Rect(x - width // 2, win_h - strip_h, width, strip_h)
    )


def draw_heatmap(
    renderer,
    heatmap: HeatmapStrip,
    position_ms: float,
    loop_bounds: tuple[int, int] | None,
    win_w: int,
    win_h: int,
) -> None:
    import pygame
    from pygame._sdl2.video import Texture

    strip_h = heatmap.height
    if strip_h <= 0:
        return
    row = np.asarray(heatmap.colors, dtype=np.uint8)
    rgba = np.empty((strip_h, len(row), 4), dtype=np.uint8)
    rgba[:, :, :3] = row[np.newaxis, :, :]
    rgba[:, :, 3] = _HEATMAP_ALPHA
    surface = pygame.image.frombuffer(rgba.tobytes(), (len(row), strip_h), "RGBA")
    Texture.from_surface(renderer, surface).draw(
        dstrect=pygame.Rect(0, win_h - strip_h, win_w, strip_h)
    )

    start_ms, end_ms = heatmap.window
    if heatmap.record_in_ms is not None:
        x = time_to_x(heatmap.record_in_ms, start_ms, end_ms, win_w)
        _draw_mark(renderer, x, _BOUND_MARK_W, strip_h, win_h, _RED)
    if loop_bounds is not None:
        for bound_ms in loop_bounds:
            x = time_to_x(bound_ms, start_ms, end_ms, win_w)
            _draw_mark(renderer, x, _BOUND_MARK_W, strip_h, win_h, _AMBER)
    x = time_to_x(position_ms, start_ms, end_ms, win_w)
    _draw_mark(renderer, x, 1, strip_h, win_h, _WHITE)
