from __future__ import annotations

from pathlib import Path

import numpy as np
import pygame
from PIL import Image
from pygame._sdl2.video import Renderer, Texture, Window

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
from .layout import compute_video_rects

# Near-black magenta used as the Win32 color key for HUD transparency.
# Any pixel drawn in this exact color becomes fully transparent.
HUD_COLOR_KEY = (1, 0, 1)


def get_window_chrome_height() -> int:
    """The title bar + frame a bordered window costs at the top, so the client
    area can be sized down to keep the video inside the rect.  Zero off Windows,
    and zero for a borderless window, which has no chrome to measure."""
    try:
        import ctypes
        SM_CYCAPTION = 4
        SM_CYFRAME = 33
        SM_CXPADDEDBORDER = 92
        user32 = ctypes.windll.user32
        return (
            user32.GetSystemMetrics(SM_CYCAPTION)
            + user32.GetSystemMetrics(SM_CYFRAME)
            + user32.GetSystemMetrics(SM_CXPADDEDBORDER)
        )
    except Exception:
        return 0


def hud_window_identity(
    active: bool,
    *,
    base_title: str,
    base_icon: Path | None,
    hybrid_title: str | None,
    hybrid_icon: Path | None,
) -> tuple[str, Path | None]:
    """The window title + icon for the HUD state: the Hybrid identity while the
    HUD is on (Fun Time Hybrid mode) when one was supplied, else Genau's own."""
    if active and hybrid_title is not None:
        return hybrid_title, hybrid_icon if hybrid_icon is not None else base_icon
    return base_title, base_icon


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
        hybrid_title: str | None = None,
        hybrid_icon_path: Path | None = None,
        borderless: bool = False,
    ) -> None:
        # Before the window exists, and before pygame.init(): SDL otherwise eats
        # the click that focuses this window, so every press on the console has
        # to be made twice — once to wake the window, once to hit the button.
        # See player_core.sdl_hints for the whole mechanism.
        deliver_the_focusing_click()
        pygame.init()
        # Borderless under Fun Time, like the satellites and Nau: with no chrome
        # the client area is the whole rect Fun Time sizes the window to — and,
        # in Hybrid, this transparent layer lines up with Nau's video beneath it
        # pixel for pixel, where a title bar on one and not the other would
        # shift them apart.  The main slot's mode is drawn on the in-video HUD,
        # so the bar would carry nothing.
        # Standalone it keeps its chrome, so it can be dragged and closed like any
        # window, and the client is sized down to leave the video inside the rect.
        if borderless:
            self.window = Window(title, size=(width, height), borderless=True)
            self.window.position = (x, y)
        else:
            chrome = get_window_chrome_height()
            self.window = Window(title, size=(width, max(1, height - chrome)))
            self.window.position = (x, y + chrome)
        load_window_icon(self.window, icon_path)
        # Fun Time Hybrid mode shows this window as "Hybrid Nau+Genau" with its
        # own icon; genau mode is plain "Genau".  Driven off the HUD toggle.
        self._base_title = title
        self._base_icon_path = icon_path
        self._hybrid_title = hybrid_title
        self._hybrid_icon_path = hybrid_icon_path
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
        # When blank, the window paints solid black and draws no clip or overlay.
        # Genau uses this while it isn't the active display (e.g. Nau mode), so an
        # alt-tab never lands on a frozen last frame.  HUD mode overrides it: a
        # transparent HUD must keep letting the window beneath show through.
        self._blank: bool = False

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

    def press_volume_at(self, mx: int, my: int) -> str:
        """The command a press at ``(mx, my)`` posts on the volume chip, "" over none.

        The new level is shown at once and asked for at the same time: Fun Time
        holds the authority and its answer is a tick away, so a slider that waited
        for it would drag a frame behind the pointer.  Its answer overwrites this
        one either way, which is what corrects a press it decides to ignore.
        """
        win_w, win_h = self.window.size
        cx, cy = chip_local(mx, my, win_w=win_w, win_h=win_h, timeline_h=0)
        part = hit_part(cx, cy)
        if part == "mute":
            muted = not self._volume.muted
            self._volume = VolumeHud(volume=self._volume.volume, muted=muted)
            return "audio_mute" if muted else "audio_unmute"
        if part == "track":
            level = volume_at(cx)
            self._volume = VolumeHud(volume=level, muted=False)
            return f"audio_set_volume|{level}"
        return ""

    def set_console_hover(self, mx: int, my: int) -> None:
        """Remember where the cursor is over the console, so a button under it
        names itself; forgotten when it is over nothing."""
        self._console_hover = self._console_painter.hover_at(mx, my)

    def set_blank(self, blank: bool) -> None:
        self._blank = blank

    def display_frame(self, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        self._video_size = (w, h)
        surface = pygame.image.frombuffer(frame.tobytes(), (w, h), "RGB")
        self._current_texture = Texture.from_surface(self.renderer, surface)
        if self._console is None:
            self._present_scene()

    def present(self) -> None:
        self._present_scene()

    def _present_scene(self) -> None:
        # HUD wins over blank: a transparent HUD must keep the color key so the
        # window beneath shows through, never a black fill over it.
        if self.hud_active:
            self.renderer.draw_color = HUD_COLOR_KEY + (255,)
        else:
            self.renderer.draw_color = (0, 0, 0, 255)
        self.renderer.clear()

        show_clip = not self.hud_active and not self._blank
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
        # Not while the HUD is on: that is Hybrid, where this window is a
        # transparent layer over Nau's and Nau draws the console over its own
        # video.  Drawing it here too would put the same console on screen twice.
        if not self._blank and not self.hud_active and self._console is not None:
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

        Beside the console, and drawn under the same condition: in Hybrid this
        window is a transparent layer over Nau's, and Nau draws both there — a
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
        title, icon = hud_window_identity(
            active,
            base_title=self._base_title,
            base_icon=self._base_icon_path,
            hybrid_title=self._hybrid_title,
            hybrid_icon=self._hybrid_icon_path,
        )
        # Set the title BEFORE _apply_layered_window: the HUD transparency finds
        # this window by its live title, so it must already be the new one.
        self.window.title = title
        load_window_icon(self.window, icon)
        self._apply_layered_window(active)

    def _find_hwnd(self) -> int:
        """Find this window's HWND via Win32 FindWindowW.

        pygame.display.get_wm_info() only works with pygame.display windows,
        not pygame._sdl2.video.Window objects.
        """
        import ctypes
        hwnd = ctypes.windll.user32.FindWindowW(None, self.window.title)
        return hwnd

    def _apply_layered_window(self, enable: bool) -> None:
        """Toggle Win32 layered-window color key transparency.

        When enabled, pixels matching HUD_COLOR_KEY (1, 0, 1) become fully
        transparent, letting Nau's video window beneath show through.
        """
        import ctypes
        import logging

        logger = logging.getLogger(__name__)
        hwnd = self._find_hwnd()
        if not hwnd:
            logger.warning("HUD: could not find window HWND for title %r", self.window.title)
            return

        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x80000
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if enable:
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED,
            )
            LWA_COLORKEY = 0x1
            # Win32 COLORREF is 0x00BBGGRR
            colorkey = HUD_COLOR_KEY[0] | (HUD_COLOR_KEY[1] << 8) | (HUD_COLOR_KEY[2] << 16)
            result = ctypes.windll.user32.SetLayeredWindowAttributes(
                hwnd, colorkey, 0, LWA_COLORKEY,
            )
            if not result:
                logger.warning("HUD: SetLayeredWindowAttributes failed (error %d)",
                               ctypes.windll.kernel32.GetLastError())
            else:
                logger.info("HUD: layered window enabled (hwnd=%#x, colorkey=%#08x)", hwnd, colorkey)
        else:
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE, style & ~WS_EX_LAYERED,
            )
            logger.info("HUD: layered window disabled")

    def destroy(self) -> None:
        self._current_texture = None
        self.window.destroy()
        pygame.quit()
