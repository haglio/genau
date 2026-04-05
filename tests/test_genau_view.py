from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest


@pytest.fixture
def mock_pygame():
    with patch.dict("sys.modules", {
        "pygame": MagicMock(),
        "pygame._sdl2": MagicMock(),
        "pygame._sdl2.video": MagicMock(),
    }) as mocked:
        yield mocked["pygame"]


def test_pygame_view_creates_window_and_renderer(mock_pygame):
    from genau.pygame_view import PygameView

    view = PygameView(width=1200, height=900, x=10, y=20, title="Genau")

    assert view.width == 1200
    assert view.height == 900
    mock_pygame.init.assert_called_once()


def test_pygame_view_get_size_delegates_to_window(mock_pygame):
    from genau.pygame_view import PygameView

    view = PygameView(width=800, height=600)
    view.window.size = (800, 600)

    assert view.get_size() == (800, 600)


def test_cruise_indicator_drawn_in_top_right_of_window(mock_pygame):
    """Cruise indicator should appear in top-right corner, not on the speed bar."""
    import sys
    from genau.pygame_view import PygameView
    from genau.refresh_controller import DirectOverlayData

    mock_pygame.Rect = lambda x, y, w, h: (x, y, w, h)
    mock_pygame.SRCALPHA = 0

    font_mock = MagicMock()
    text_surf = MagicMock()
    text_surf.get_width.return_value = 50
    text_surf.get_height.return_value = 14
    font_mock.render.return_value = text_surf

    view = PygameView(width=800, height=600)
    view.window.size = (800, 600)
    view._overlay_font = font_mock

    Texture = sys.modules["pygame._sdl2.video"].Texture
    texture_mock = Texture.from_surface.return_value
    texture_mock.draw.reset_mock()

    data = DirectOverlayData(
        speed=5, bpm=120.0, amplitude=50, center=50,
        waveform_points=[0.5] * 10, position=5000, cruise_active=True,
    )
    view.set_direct_overlay(data)
    view._draw_direct_overlay()

    draw_calls = texture_mock.draw.call_args_list
    assert len(draw_calls) == 2, "Expected panel + cruise indicator textures"

    cruise_rect = draw_calls[1].kwargs["dstrect"]
    cx, cy, _cw, _ch = cruise_rect
    assert cx > 400, f"Cruise x={cx} should be in right half of 800px window"
    assert cy < 50, f"Cruise y={cy} should be near top of window"
