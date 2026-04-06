from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pygame
from PIL import Image
from pygame._sdl2.video import Renderer, Texture, Window

if TYPE_CHECKING:
    from .refresh_controller import DirectOverlayData


def _get_window_chrome_height() -> int:
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
    ) -> None:
        pygame.init()
        chrome_height = _get_window_chrome_height()
        client_height = max(1, height - chrome_height)
        self.window = Window(title, size=(width, client_height))
        self.window.position = (x, y + chrome_height)
        if icon_path is not None and icon_path.exists():
            try:
                pil_icon = Image.open(str(icon_path))
                pil_icon = pil_icon.convert("RGBA")
                icon_surface = pygame.image.frombuffer(
                    pil_icon.tobytes(), pil_icon.size, "RGBA"
                )
                self.window.set_icon(icon_surface)
            except Exception:
                pass
        self.renderer = Renderer(self.window, accelerated=True)
        self.clock = pygame.time.Clock()
        self._width = width
        self._height = height
        self._current_texture: Texture | None = None
        self._loading_font: pygame.font.Font | None = None
        self._loading_text: str | None = None
        self._direct_overlay: DirectOverlayData | None = None
        self._overlay_font: pygame.font.Font | None = None

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

    def display_frame(self, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        surface = pygame.image.frombuffer(frame.tobytes(), (w, h), "RGB")
        self._current_texture = Texture.from_surface(self.renderer, surface)
        if self._direct_overlay is None:
            self._present_scene()

    def present(self) -> None:
        self._present_scene()

    def _present_scene(self) -> None:
        self.renderer.clear()
        if self._current_texture is not None:
            self._current_texture.draw()
        if self._loading_text:
            self._draw_loading_overlay()
        if self._direct_overlay is not None:
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

    def show(self) -> None:
        self.window.show()

    def hide(self) -> None:
        self.window.hide()

    def destroy(self) -> None:
        self._current_texture = None
        self.window.destroy()
        pygame.quit()
