"""What Genau draws, in the window :mod:`genau.window` made for it.

One frame is a clip (or nothing, while the HUD is on and this window is a
see-through layer over Nau's), the loading line, and — in genau mode, where
this window IS the primary display — the main console and the volume chip the
whole family shares.

The window itself is not here: how the rect is chosen, what the caption says
and whether Windows lets the desktop show through are the window's decisions,
and none of them changes because of what is on screen.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pygame
from player_core.console_hud import hud_xy
from pygame._sdl2.video import Texture

from .console_panel import ConsolePanel
from .layout import compute_video_rects
from .volume_chip import VolumeChip
from .window import HUD_COLOR_KEY, GenauWindow


class PygameView:
    def __init__(
        self,
        *,
        width: int,
        height: int,
        x: int = 0,
        y: int = 0,
        console: ConsolePanel,
        volume: VolumeChip,
        title: str = "Genau",
        icon_path: Path | None = None,
        video_title: str | None = None,
    ) -> None:
        self.window = GenauWindow(
            width=width, height=height, x=x, y=y, title=title,
            icon_path=icon_path, video_title=video_title)
        self.renderer = self.window.renderer
        self.clock = self.window.clock
        self._current_texture: Texture | None = None
        self._video_size: tuple[int, int] | None = None
        self._loading_font: pygame.font.Font | None = None
        self._loading_text: str | None = None
        # The two things this window draws over its clip in genau mode, and the
        # two the pointer presses: one of each, built where the app is wired, so
        # what is drawn and what is hit are the same surface.
        self._console = console
        self._volume = volume

    @property
    def width(self) -> int:
        return self.window.width

    @property
    def height(self) -> int:
        return self.window.height

    @property
    def hud_active(self) -> bool:
        return self.window.hud_active

    def get_size(self) -> tuple[int, int]:
        return self.window.size

    def set_loading_text(self, text: str | None) -> None:
        self._loading_text = text

    def blit_frame(self, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        self._video_size = (w, h)
        surface = pygame.image.frombuffer(frame.tobytes(), (w, h), "RGB")
        self._current_texture = Texture.from_surface(self.renderer, surface)
        if not self._console.showing:
            self._present_scene()

    def present(self) -> None:
        self._present_scene()

    def set_hud_mode(self, active: bool) -> None:
        self.window.set_hud_mode(active)

    def destroy(self) -> None:
        self._current_texture = None
        self.window.destroy()

    def _present_scene(self) -> None:
        # The HUD keeps the color key so the window beneath shows through.
        if self.hud_active:
            self.renderer.draw_color = HUD_COLOR_KEY + (255,)
        else:
            self.renderer.draw_color = (0, 0, 0, 255)
        self.renderer.clear()

        show_clip = not self.hud_active
        if show_clip and self._current_texture is not None:
            if self._video_size is not None:
                win_w, win_h = self.window.size
                rects = compute_video_rects(*self._video_size, win_w, win_h)
                for x, y, w, h in rects:
                    self._current_texture.draw(dstrect=pygame.Rect(x, y, w, h))
            else:
                self._current_texture.draw()
        if show_clip and self._loading_text:
            self._draw_loading_overlay()
        # Not while the HUD is on: that is video mode, where this window is a
        # see-through layer over Nau's and Nau draws the console over its own
        # video.  Drawing it here too would put the same console on screen twice.
        if not self.hud_active and self._console.showing:
            self._draw_console()
            self._draw_volume()
        self.renderer.present()

    def _draw_loading_overlay(self) -> None:
        if self._loading_font is None:
            self._loading_font = pygame.font.SysFont("arial", 18)
        text_surface = self._loading_font.render(self._loading_text, True, (255, 255, 255))
        padding = 8
        w, h = text_surface.get_size()
        bg = pygame.Surface((w + padding * 2, h + padding * 2), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 180))
        bg.blit(text_surface, (padding, padding))
        texture = Texture.from_surface(self.renderer, bg)
        win_w, _win_h = self.window.size
        dest = pygame.Rect(win_w - w - padding * 3, padding, w + padding * 2, h + padding * 2)
        texture.draw(dstrect=dest)

    def _draw_console(self) -> None:
        """Blit the main console, painted by the module every player shares.

        In genau mode Genau is on screen, so it draws the console Nau draws in the
        other modes — the same painter, so the panel reads the same whichever
        player is showing it, and there is one place to change it.
        """
        painted = self._console.rgba()
        if painted is None:
            return
        rgba, size = painted
        surface = pygame.image.frombuffer(rgba, size, "RGBA")
        texture = Texture.from_surface(self.renderer, surface)
        texture.draw(dstrect=pygame.Rect(hud_xy(), size))

    def _draw_volume(self) -> None:
        """Blit the primary display's volume chip, lower-right.

        Beside the console, and drawn under the same condition: in video mode
        this window is a see-through layer over Nau's, and Nau draws both there — a
        chip here too would put two sliders on screen disagreeing about which
        press the level came from.
        """
        win_w, win_h = self.window.size
        rgba, size = self._volume.rgba()
        surface = pygame.image.frombuffer(rgba, size, "RGBA")
        texture = Texture.from_surface(self.renderer, surface)
        vx, vy = self._volume.corner(win_w=win_w, win_h=win_h)
        texture.draw(dstrect=pygame.Rect(vx, vy, *size))
