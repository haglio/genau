"""On-screen state feedback for Nau: corner indicator + recording filmstrip.

The pure decision logic (which icon, when to capture a thumbnail, strip
geometry) lives here untied to pygame so it is unit-testable; the drawing
helpers at the bottom turn those decisions into textures.
"""
from __future__ import annotations

import numpy as np


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


def draw_strip(renderer, strip: RecordingStrip, position_ms: float, win_h: int) -> None:
    import pygame
    from pygame._sdl2.video import Texture

    bar_w = strip.bar_width_px(position_ms)
    if bar_w <= 0:
        return
    tile_h = strip.tile_height
    top = win_h - tile_h

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
