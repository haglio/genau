from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pygame
from PIL import Image
from pygame._sdl2.video import Renderer, Texture, Window

from .layout import compute_video_rects

if TYPE_CHECKING:
    from .refresh_controller import DirectOverlayData

# Near-black magenta used as the Win32 color key for HUD transparency.
# Any pixel drawn in this exact color becomes fully transparent.
HUD_COLOR_KEY = (1, 0, 1)


def get_window_chrome_height() -> int:
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
    ) -> None:
        pygame.init()
        chrome_height = get_window_chrome_height()
        client_height = max(1, height - chrome_height)
        self.window = Window(title, size=(width, client_height))
        self.window.position = (x, y + chrome_height)
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
        self._direct_overlay: DirectOverlayData | None = None
        self._overlay_font: pygame.font.Font | None = None
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

    def set_direct_overlay(self, data: DirectOverlayData | None) -> None:
        self._direct_overlay = data

    def set_blank(self, blank: bool) -> None:
        self._blank = blank

    def display_frame(self, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        self._video_size = (w, h)
        surface = pygame.image.frombuffer(frame.tobytes(), (w, h), "RGB")
        self._current_texture = Texture.from_surface(self.renderer, surface)
        if self._direct_overlay is None:
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
        if not self._blank and self._direct_overlay is not None:
            self._draw_direct_overlay()
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

    def _draw_direct_overlay(self) -> None:
        data = self._direct_overlay
        if data is None:
            return
        if self._overlay_font is None:
            self._overlay_font = pygame.font.SysFont("consolas", 12)

        wave_w, wave_h = 160, 60
        amp_bar_w = 20
        spd_bar_h = 16
        pad = 8
        gap = 4

        panel_w = pad + wave_w + gap + amp_bar_w + pad
        panel_h = pad + spd_bar_h + gap + wave_h + pad

        surface = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        surface.fill((0, 0, 0, 160))

        # --- Speed bar above waveform ---
        spd_x, spd_y = pad, pad
        pps = data.phase_per_second
        cycle_frac = min(1.0, 1.0 / (pps * data.display_seconds)) if pps > 0 else 1.0
        spd_fill_w = max(4, int(cycle_frac * wave_w))
        pygame.draw.rect(surface, (60, 60, 60), (spd_x, spd_y, wave_w, spd_bar_h))
        pygame.draw.rect(surface, (80, 180, 80), (spd_x, spd_y, spd_fill_w, spd_bar_h))
        spd_text = self._overlay_font.render(f"SPD {data.speed}", True, (220, 220, 220))
        surface.blit(spd_text, (spd_x + 3, spd_y + 1))

        # --- Waveform graph (scrolling) ---
        wave_x = pad
        wave_y = pad + spd_bar_h + gap
        points = data.waveform_points
        if len(points) >= 2:
            coords = []
            for i, val in enumerate(points):
                x = wave_x + int(i / (len(points) - 1) * (wave_w - 1))
                y = wave_y + int((1 - val) * (wave_h - 1))
                coords.append((x, y))
            pygame.draw.lines(surface, (100, 200, 255), False, coords, 2)

        # Center dotted line through waveform
        center_norm = data.center / 100
        ctr_y = wave_y + int((1 - center_norm) * (wave_h - 1))
        for dx in range(0, wave_w, 6):
            x1 = wave_x + dx
            x2 = min(wave_x + dx + 3, wave_x + wave_w - 1)
            pygame.draw.line(surface, (200, 200, 100, 180), (x1, ctr_y), (x2, ctr_y), 1)

        # Highlight dot on left edge at current position
        pos_norm = data.position / 9999
        dot_y = wave_y + int((1 - pos_norm) * (wave_h - 1))
        pygame.draw.circle(surface, (255, 255, 100), (wave_x, dot_y), 4)

        # Waveform border
        pygame.draw.rect(surface, (80, 80, 80), (wave_x, wave_y, wave_w, wave_h), 1)

        # --- Amplitude bar to the right of waveform ---
        amp_x = wave_x + wave_w + gap
        amp_y = wave_y
        # Bar height and position reflect amplitude and center
        amp_frac = data.amplitude / 100
        ctr_frac = data.center / 100
        bar_h = max(2, int(amp_frac * wave_h))
        bar_top = amp_y + int((1 - ctr_frac) * wave_h - bar_h / 2)
        bar_top = max(amp_y, min(amp_y + wave_h - bar_h, bar_top))
        pygame.draw.rect(surface, (60, 60, 60), (amp_x, amp_y, amp_bar_w, wave_h))
        pygame.draw.rect(surface, (100, 160, 255), (amp_x, bar_top, amp_bar_w, bar_h))
        # AMP label
        amp_label = self._overlay_font.render(f"{data.amplitude}", True, (220, 220, 220))
        label_y = bar_top + (bar_h - amp_label.get_height()) // 2
        label_y = max(amp_y, min(amp_y + wave_h - amp_label.get_height(), label_y))
        label_x = amp_x + (amp_bar_w - amp_label.get_width()) // 2
        surface.blit(amp_label, (label_x, label_y))

        if data.cruise_active:
            cc_text = self._overlay_font.render("CC", True, (255, 200, 100))
            surface.blit(
                cc_text, (panel_w - cc_text.get_width() - pad, pad + 1)
            )

        texture = Texture.from_surface(self.renderer, surface)
        dest = pygame.Rect(pad, pad, panel_w, panel_h)
        texture.draw(dstrect=dest)

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
