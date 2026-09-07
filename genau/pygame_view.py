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

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pygame
from player_core.console_hud import ConsoleHud, ConsolePainter, hud_xy
from player_core.volume import (
    VolumeHud,
    VolumeHudPainter,
    chip_local,
    chip_xy,
    hit_part,
    volume_at,
)
from pygame._sdl2.video import Texture

from .layout import compute_video_rects
from .window import HUD_COLOR_KEY, GenauWindow


@dataclass(frozen=True)
class VolumePress:
    """What a press on the volume chip asks for, and what to show meanwhile.

    Fun Time holds the authority over the level and its answer is a tick away,
    so a slider that waited for it would trail the pointer by a frame.  The
    chip shows this at once; Fun Time's answer overwrites it either way, which
    is what corrects a press it decides to ignore.
    """

    command: str
    level: int
    muted: bool


class PygameView:
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
        self.window = GenauWindow(
            width=width, height=height, x=x, y=y, title=title,
            icon_path=icon_path, video_title=video_title)
        self.renderer = self.window.renderer
        self.clock = self.window.clock
        self._current_texture: Texture | None = None
        self._video_size: tuple[int, int] | None = None
        self._loading_font: pygame.font.Font | None = None
        self._loading_text: str | None = None
        # In genau mode Genau draws the whole main console — the same one Nau
        # draws over its video in the other modes — into its own window, and takes
        # its clicks.  None until the refresh loop has one to show.
        self._console: ConsoleHud | None = None
        self._console_painter = ConsolePainter()
        self._console_hover: tuple[int, int] | None = None
        # The primary display's volume chip, in the corner Nau puts it in — this
        # window IS the primary display in genau mode, and reaching for the sound
        # should not mean finding a different control depending on the mode.
        # Fun Time owns the level and tells us what it is; a press asks it.
        self._volume = VolumeHud()
        self._volume_painter = VolumeHudPainter()

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

    def set_console(self, console: ConsoleHud | None) -> None:
        self._console = console

    def console_press_at(self, mx: int, my: int) -> str:
        """The command a press at ``(mx, my)`` posts on the console, "" over none.

        A press on one of the drive readout's bars takes hold of it, so the pointer
        goes on setting that level until :meth:`console_release`.
        """
        return self._console_painter.press_at(mx, my)

    def console_drag_to(self, mx: int, my: int) -> str:
        """The command the pointer posts while a bar is held, "" while none is."""
        return self._console_painter.drag_to(mx, my)

    def console_release(self) -> None:
        """Let go of whichever bar a press took hold of."""
        self._console_painter.release()

    def set_console_hover(self, mx: int, my: int) -> None:
        """Remember where the cursor is over the console, so a button under it
        names itself; forgotten when it is over nothing."""
        self._console_hover = self._console_painter.hover_at(mx, my)

    def set_volume(self, level: int, muted: bool) -> None:
        """Show the level Fun Time is publishing for the primary display."""
        self._volume = VolumeHud(volume=level, muted=muted)

    def volume_press_at(self, mx: int, my: int) -> VolumePress | None:
        """What a press at ``(mx, my)`` on the volume chip asks for, or None
        over no part of it.

        A question, not a move: it says what to ask Fun Time for *and* what the
        chip should show meanwhile, and the caller does both.  Showing it here
        made a hit test that also mutated, which is why nothing could ask what a
        press would do without it having already happened.
        """
        win_w, win_h = self.window.size
        cx, cy = chip_local(mx, my, win_w=win_w, win_h=win_h, timeline_h=0)
        part = hit_part(cx, cy)
        if part == "mute":
            muted = not self._volume.muted
            return VolumePress(
                command="audio_mute" if muted else "audio_unmute",
                level=self._volume.volume,
                muted=muted,
            )
        if part == "track":
            level = volume_at(cx)
            return VolumePress(
                command=f"audio_set_volume|{level}", level=level, muted=False)
        return None

    def blit_frame(self, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        self._video_size = (w, h)
        surface = pygame.image.frombuffer(frame.tobytes(), (w, h), "RGB")
        self._current_texture = Texture.from_surface(self.renderer, surface)
        if self._console is None:
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
        if not self.hud_active and self._console is not None:
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
        console = self._console
        if console is None:
            return
        rgba, size = self._console_painter.rgba(console, hover=self._console_hover)
        surface = pygame.image.frombuffer(rgba, size, "RGBA")
        texture = Texture.from_surface(self.renderer, surface)
        texture.draw(dstrect=pygame.Rect(hud_xy(), size))

    def _draw_volume(self) -> None:
        """Blit the primary display's volume chip, lower-right.

        Beside the console, and drawn under the same condition: in video mode
        this window is a see-through layer over Nau's, and Nau draws both there — a
        chip here too would put two sliders on screen disagreeing about which
        press the level came from.  ``timeline_h=0`` says there is no scrubber
        under it, which is what this window has and Nau's does not; the chip
        still lands in the same pixels Nau's does.
        """
        win_w, win_h = self.window.size
        rgba, size = self._volume_painter.rgba(self._volume)
        surface = pygame.image.frombuffer(rgba, size, "RGBA")
        texture = Texture.from_surface(self.renderer, surface)
        vx, vy = chip_xy(win_w=win_w, win_h=win_h, timeline_h=0)
        texture.draw(dstrect=pygame.Rect(vx, vy, *size))
