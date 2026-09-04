from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pygame
from PIL import Image
from player_core.console_hud import ConsoleHud, ConsolePainter, hud_xy
from player_core.sdl_hints import deliver_the_focusing_click
from player_core.volume import (
    VolumeHud,
    VolumeHudPainter,
    chip_local,
    chip_xy,
    hit_part,
    volume_at,
)
from pygame._sdl2.video import Renderer, Texture, Window

from .layout import compute_video_rects

# Near-black magenta used as the Win32 color key for HUD transparency.
# Any pixel drawn in this exact color becomes fully transparent.
HUD_COLOR_KEY = (1, 0, 1)


def hud_window_identity(active: bool, *, base_title: str, video_title: str | None) -> str:
    """The window's caption for the HUD state: the video-mode one while the HUD
    is on, when one was supplied, else Genau's own."""
    if active and video_title is not None:
        return video_title
    return base_title


@dataclass(frozen=True)
class VolumePress:
    """What a press on the volume chip asks for, and what to show meanwhile.

    Fun Time holds the authority over the level and its answer is a tick away,
    so a slider that waited for it would drag a frame behind the pointer.  The
    chip shows this at once; Fun Time's answer overwrites it either way, which
    is what corrects a press it decides to ignore.
    """

    command: str
    level: int
    muted: bool


def _layered_window(title: str):
    """This window's transparency, or None where there is no Win32 to ask.

    genau.win32 imports on any platform (it binds its DLLs through a loader that
    says so rather than raising), but there is nothing to find off Windows, so
    the view carries no transparency at all rather than one that refuses.
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
        pil_icon = Image.open(str(icon_path)).convert("RGBA")
        icon_surface = pygame.image.frombuffer(
            pil_icon.tobytes(), pil_icon.size, "RGBA"
        )
        window.set_icon(icon_surface)
    except Exception:
        pass


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
        self.hud_active: bool = False

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

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

    def set_console_hover(self, mx: int, my: int) -> None:
        """Remember where the cursor is over the console, so a button under it
        names itself; forgotten when it is over nothing."""
        self._console_hover = self._console_painter.hover_at(mx, my)

    def blit_frame(self, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        self._video_size = (w, h)
        surface = pygame.image.frombuffer(frame.tobytes(), (w, h), "RGB")
        self._current_texture = Texture.from_surface(self.renderer, surface)
        if self._console is None:
            self._present_scene()

    def present(self) -> None:
        self._present_scene()

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
        """Blit the primary display's volume chip, bottom-right.

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
        self._current_texture = None
        self.window.destroy()
        pygame.quit()
