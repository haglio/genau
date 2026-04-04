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
            self._overlay_font = pygame.font.SysFont("consolas", 14)

        wave_w, wave_h = 120, 60
        bar_w = 15
        pad = 8
        gap = 4

        panel_w = pad + wave_w + gap + bar_w + pad
        font_h = self._overlay_font.get_height()
        text_h = font_h * 2 + 2
        panel_h = pad + wave_h + gap + text_h + pad

        surface = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        surface.fill((0, 0, 0, 160))

        # Waveform graph
        wave_x, wave_y = pad, pad
        points = data.waveform_points
        if len(points) >= 2:
            coords = []
            for i, val in enumerate(points):
                x = wave_x + int(i / (len(points) - 1) * (wave_w - 1))
                y = wave_y + int((1 - val) * (wave_h - 1))
                coords.append((x, y))
            pygame.draw.lines(surface, (100, 200, 255), False, coords, 2)

            # Playhead dot
            idx = int(data.phase_frac * (len(points) - 1))
            idx = max(0, min(len(points) - 1, idx))
            px = wave_x + int(idx / (len(points) - 1) * (wave_w - 1))
            py = wave_y + int((1 - points[idx]) * (wave_h - 1))
            pygame.draw.circle(surface, (255, 255, 100), (px, py), 4)

        # Waveform border
        pygame.draw.rect(surface, (80, 80, 80), (wave_x, wave_y, wave_w, wave_h), 1)

        # Position bar
        bar_x = wave_x + wave_w + gap
        bar_y = wave_y
        pygame.draw.rect(surface, (80, 80, 80), (bar_x, bar_y, bar_w, wave_h), 1)
        fill_h = int(data.position / 9999 * (wave_h - 2))
        if fill_h > 0:
            pygame.draw.rect(
                surface,
                (100, 255, 100),
                (bar_x + 1, bar_y + wave_h - 1 - fill_h, bar_w - 2, fill_h),
            )

        # Text row 1: speed + amplitude
        text_y = wave_y + wave_h + gap
        line1 = f"SPD {data.speed_level}  AMP {data.amplitude}%"
        surf1 = self._overlay_font.render(line1, True, (200, 200, 200))
        surface.blit(surf1, (pad, text_y))

        # Text row 2: center + auto
        line2 = f"CTR {data.center}%"
        if data.auto_active:
            line2 += "  AUTO"
        surf2 = self._overlay_font.render(line2, True, (200, 200, 200))
        surface.blit(surf2, (pad, text_y + font_h + 2))

        texture = Texture.from_surface(self.renderer, surface)
        win_w, win_h = self.window.size
        dest = pygame.Rect(win_w - panel_w - pad, win_h - panel_h - pad, panel_w, panel_h)
        texture.draw(dstrect=dest)

    def show(self) -> None:
        self.window.show()

    def hide(self) -> None:
        self.window.hide()

    def set_title(self, title: str) -> None:
        self.window.title = title

    def destroy(self) -> None:
        self._current_texture = None
        self.window.destroy()
        pygame.quit()
