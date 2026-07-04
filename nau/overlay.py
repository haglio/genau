"""On-screen state feedback for Nau: indicator, filmstrip, funscript heatmap.

The pure decision logic (which icon, when to capture a thumbnail, strip
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


class RecordingStrip:
    """Filmstrip that grows along the bottom edge while a loop is recorded.

    One thumbnail is captured per recorded second (the first immediately),
    and the bar advances continuously between captures — tile-width pixels
    per second, capped at *max_width*.
    """

    def __init__(self, *, tile_height: int, max_width: int) -> None:
        self._tile_height = tile_height
        self._max_width = max_width
        self._start_ms: float | None = None
        self._tile_width: int | None = None
        self._thumbs: list[np.ndarray] = []

    @property
    def thumbnails(self) -> list[np.ndarray]:
        return self._thumbs

    @property
    def tile_height(self) -> int:
        return self._tile_height

    def update(self, loop_state: str, position_ms: float, frame: np.ndarray | None) -> None:
        if loop_state != "recording":
            self._start_ms = None
            self._tile_width = None
            self._thumbs = []
            return
        if self._start_ms is None:
            self._start_ms = position_ms
        self._maybe_capture(position_ms, frame)

    def _maybe_capture(self, position_ms: float, frame: np.ndarray | None) -> None:
        if frame is None:
            return
        elapsed = position_ms - self._start_ms
        if elapsed < len(self._thumbs) * 1000.0:
            return
        import cv2

        h, w = frame.shape[:2]
        tile_w = self._tile_width or max(1, round(self._tile_height * w / h))
        if (len(self._thumbs) + 1) * tile_w > self._max_width:
            return
        thumb = cv2.resize(frame, (tile_w, self._tile_height), interpolation=cv2.INTER_AREA)
        self._tile_width = tile_w
        self._thumbs.append(thumb)

    def bar_width_px(self, position_ms: float) -> int:
        if self._start_ms is None or self._tile_width is None:
            return 0
        elapsed = position_ms - self._start_ms
        return min(self._max_width, int(elapsed / 1000.0 * self._tile_width))


_HEATMAP_HEIGHT = 8


class HeatmapStrip:
    """Full-duration funscript heatmap pinned to the window's bottom edge.

    The color row is expensive to build (one bucket per pixel), so update()
    rebuilds only when the video or the width changes.
    """

    def __init__(self) -> None:
        self._key: tuple | None = None
        self._colors: list[tuple[int, int, int]] = []

    @property
    def colors(self) -> list[tuple[int, int, int]]:
        return self._colors

    @property
    def height(self) -> int:
        """Strip height in px — 0 when there is nothing to draw."""
        return _HEATMAP_HEIGHT if self._colors else 0

    def update(self, video_key, funscript, duration_ms: float, width: int) -> None:
        key = (video_key, width)
        if key == self._key:
            return
        self._key = key
        if funscript is None:
            self._colors = []
        else:
            self._colors = build_heatmap(funscript, duration_ms, max(1, width))


def cursor_x(position_ms: float, duration_ms: float, width: int) -> int:
    """Strip x for a timestamp: position_ms/duration_ms of width, kept on-strip."""
    if duration_ms <= 0:
        return 0
    return max(0, min(width - 1, int(position_ms / duration_ms * width)))


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


def draw_strip(renderer, strip: RecordingStrip, position_ms: float, bottom: int) -> None:
    """Draw the filmstrip with its bottom edge at y=*bottom* (stacked above
    the heatmap when one is showing)."""
    import pygame
    from pygame._sdl2.video import Texture

    bar_w = strip.bar_width_px(position_ms)
    if bar_w <= 0:
        return
    tile_h = strip.tile_height
    top = bottom - tile_h

    # Growing red underlay — visible in the gap past the last thumbnail.
    underlay = pygame.Surface((bar_w, tile_h), pygame.SRCALPHA)
    underlay.fill((180, 40, 40, 130))
    pygame.draw.rect(underlay, _RED, pygame.Rect(0, 0, bar_w, 2))
    Texture.from_surface(renderer, underlay).draw(
        dstrect=pygame.Rect(0, top, bar_w, tile_h)
    )

    x = 0
    for thumb in strip.thumbnails:
        h, w = thumb.shape[:2]
        surface = pygame.image.frombuffer(thumb.tobytes(), (w, h), "RGB")
        Texture.from_surface(renderer, surface).draw(dstrect=pygame.Rect(x, top, w, h))
        x += w


_HEATMAP_ALPHA = 178  # ~70%: present but unobtrusive under the video
_MARK_OVERHANG = 2  # cursor/loop marks poke above the strip so they read


def _draw_mark(renderer, x: int, strip_h: int, win_h: int, color) -> None:
    import pygame
    from pygame._sdl2.video import Texture

    mark_h = strip_h + _MARK_OVERHANG
    mark = pygame.Surface((1, mark_h), pygame.SRCALPHA)
    mark.fill(color)
    Texture.from_surface(renderer, mark).draw(
        dstrect=pygame.Rect(x, win_h - mark_h, 1, mark_h)
    )


def draw_heatmap(
    renderer,
    heatmap: HeatmapStrip,
    position_ms: float,
    duration_ms: float,
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

    if loop_bounds is not None:
        for bound_ms in loop_bounds:
            _draw_mark(renderer, cursor_x(bound_ms, duration_ms, win_w), strip_h, win_h, _AMBER)
    _draw_mark(renderer, cursor_x(position_ms, duration_ms, win_w), strip_h, win_h, _WHITE)
