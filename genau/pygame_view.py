from __future__ import annotations

from pathlib import Path

import numpy as np
import pygame
from PIL import Image
from pygame._sdl2.video import Renderer, Texture, Window

from .drive_hud import PANEL_SIZE as DRIVE_PANEL_SIZE
from .drive_hud import DriveHud, DriveHudPainter
from .layout import compute_video_rects

# Near-black magenta used as the Win32 color key for HUD transparency.
# Any pixel drawn in this exact color becomes fully transparent.
HUD_COLOR_KEY = (1, 0, 1)

# Where the drive readout sits in Genau's window — the top-left corner, the same
# corner every player in this family puts its HUD in.
DRIVE_HUD_XY = (8, 8)


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
    ) -> None:
        pygame.init()
        # Borderless, like the satellites and Nau: the primary slot's mode used to
        # be readable off this window's title bar, but that moved onto the in-video
        # HUD, so the bar was only taking space.  With no chrome the client area is
        # the whole rect Fun Time sizes the window to — and, in Hybrid, this
        # transparent layer lines up with Nau's video beneath it pixel for pixel,
        # where a title bar on one and not the other would shift them apart.
        self.window = Window(title, size=(width, height), borderless=True)
        self.window.position = (x, y)
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
        self._drive_hud: DriveHud | None = None
        self._drive_painter = DriveHudPainter()
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

    def set_drive_hud(self, hud: DriveHud | None) -> None:
        self._drive_hud = hud

    def set_blank(self, blank: bool) -> None:
        self._blank = blank

    def display_frame(self, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        self._video_size = (w, h)
        surface = pygame.image.frombuffer(frame.tobytes(), (w, h), "RGB")
        self._current_texture = Texture.from_surface(self.renderer, surface)
        if self._drive_hud is None:
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
        # transparent layer over Nau's and the readout is drawn inside Nau's
        # console, beneath the controls that move it.  Drawing it here too would
        # put the same panel on screen twice.
        if not self._blank and not self.hud_active and self._drive_hud is not None:
            self._draw_drive_hud()
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

    def _draw_drive_hud(self) -> None:
        """Blit the drive readout, painted by the module both players share.

        Genau used to draw this panel itself, straight into this window with
        ``pygame.draw`` calls and a Consolas SysFont — the last HUD in the family
        still doing that.  It is now the same painting Nau composites into its
        video in Hybrid, so the panel reads the same whichever player is showing
        it, and there is only one place to change it.
        """
        hud = self._drive_hud
        if hud is None:
            return
        surface = pygame.image.frombuffer(
            self._drive_painter.rgba_bytes(hud), DRIVE_PANEL_SIZE, "RGBA")
        texture = Texture.from_surface(self.renderer, surface)
        texture.draw(dstrect=pygame.Rect(DRIVE_HUD_XY, DRIVE_PANEL_SIZE))

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
        transparent, letting the window beneath (VLC) show through.
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

    def show(self) -> None:
        self.window.show()

    def hide(self) -> None:
        self.window.hide()

    def destroy(self) -> None:
        self._current_texture = None
        self.window.destroy()
        pygame.quit()
