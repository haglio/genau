"""Genau's window: the one SDL creates, and what Windows is told about it.

Four decisions that all belong to the window rather than to what is drawn in
it — the borderless geometry, the icon, the caption, and the see-through layer
video mode needs — and all four are made in an order that is load-bearing:

* the focusing click is asked for before ``pygame.init()``, because SDL decides
  then whether the click that focuses a window is also delivered to it;
* the layered-window handle is taken while the caption is still the one the
  window was made with, because Win32 finds a window by its title and the HUD
  renames this one;
* the renderer is made from the window and dies with it, which is why the two
  are one object here rather than two.
"""
from __future__ import annotations

from pathlib import Path

import pygame
from player_core.sdl_hints import deliver_the_focusing_click
from pygame._sdl2.video import Renderer, Window

# Near-black violet used as the Win32 color key for HUD transparency.
# Any pixel drawn in this exact color becomes fully transparent.
HUD_COLOR_KEY = (1, 0, 1)


def hud_window_identity(active: bool, *, base_title: str, video_title: str | None) -> str:
    """The window's caption for the HUD state: the video-mode one while the HUD
    is on, when one was supplied, else Genau's own."""
    if active and video_title is not None:
        return video_title
    return base_title


def _layered_window(title: str):
    """This window's transparency, or None where there is no Win32 to ask.

    genau.win32 imports on any platform (it binds its DLLs through a loader that
    says so rather than raising), but there is nothing to find off Windows, so
    the window carries no transparency at all rather than one that refuses.
    """
    from .win32_loader import WIN32_AVAILABLE

    if not WIN32_AVAILABLE:
        return None
    from .win32 import LayeredWindow

    return LayeredWindow(title, HUD_COLOR_KEY)


def load_window_icon(window: Window, icon_path: Path | None) -> None:
    if icon_path is None or not icon_path.exists():
        return
    try:
        from PIL import Image
        pil_icon = Image.open(str(icon_path)).convert("RGBA")
        icon_surface = pygame.image.frombuffer(
            pil_icon.tobytes(), pil_icon.size, "RGBA"
        )
        window.set_icon(icon_surface)
    except Exception:
        pass


class GenauWindow:
    def __init__(
        self,
        *,
        width: int,
        height: int,
        x: int = 0,
        y: int = 0,
        title: str = "Genau",
        icon_path: Path | None = None,
        video_title: str | None = None,
    ) -> None:
        # Before the window exists, and before pygame.init(): SDL otherwise eats
        # the click that focuses this window, so every press on the console has
        # to be made twice — once to wake the window, once to hit the button.
        # See player_core.sdl_hints for the whole mechanism.
        deliver_the_focusing_click()
        pygame.init()
        # Borderless, like the satellites and Nau: with no chrome the client area
        # is the whole rect Fun Time sizes the window to — and, in video mode,
        # this see-through layer lines up with Nau's video beneath it pixel for
        # pixel, where a title bar on one and not the other would shift them
        # apart.  The main slot's mode is drawn on the in-video HUD, so the bar
        # would carry nothing.
        self.window = Window(title, size=(width, height), borderless=True)
        self.window.position = (x, y)
        load_window_icon(self.window, icon_path)
        # Fun Time's video mode shows this window as "Video Nau+Genau"; genau
        # mode is plain "Genau".  Driven off the HUD toggle.
        self._base_title = title
        # Taken while the caption is still the one the window was made with, and
        # held: the HUD renames this window, and a handle looked up afterwards
        # would be a handle found by a caption that had just changed.
        self._layered = _layered_window(title)
        self._video_title = video_title
        self.renderer = Renderer(self.window, accelerated=True)
        self.clock = pygame.time.Clock()
        self._width = width
        self._height = height
        self.hud_active: bool = False

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def size(self) -> tuple[int, int]:
        return self.window.size

    def set_hud_mode(self, active: bool) -> None:
        if active == self.hud_active:
            return
        self.hud_active = active
        self.window.title = hud_window_identity(
            active, base_title=self._base_title, video_title=self._video_title)
        # Order-free now: the transparency holds the handle it took when the
        # window was made, so the rename above cannot reach it.
        if self._layered is not None:
            self._layered.set_transparent(active)

    def destroy(self) -> None:
        self.window.destroy()
        pygame.quit()
