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


def test_cruise_indicator_in_top_right_of_hud(mock_pygame):
    """Cruise indicator should appear in top-right corner of the HUD panel."""
    from genau.pygame_view import PygameView
    from genau.refresh_controller import DirectOverlayData

    mock_pygame.Rect = lambda x, y, w, h: (x, y, w, h)
    mock_pygame.SRCALPHA = 0

    font_mock = MagicMock()
    text_surf = MagicMock()
    text_surf.get_width.return_value = 16
    text_surf.get_height.return_value = 14
    font_mock.render.return_value = text_surf

    panel_surface = MagicMock()
    mock_pygame.Surface.return_value = panel_surface

    view = PygameView(width=800, height=600)
    view.window.size = (800, 600)
    view._overlay_font = font_mock

    data = DirectOverlayData(
        speed=5, bpm=120.0, amplitude=50, center=50,
        waveform_points=[0.5] * 10, position=5000, cruise_active=True,
    )
    view.set_direct_overlay(data)
    panel_surface.blit.reset_mock()
    view._draw_direct_overlay()

    # Find the blit call that renders the CC text
    cc_blits = [
        c for c in panel_surface.blit.call_args_list
        if c.args[0] is text_surf
    ]
    assert len(cc_blits) >= 1, "CC text should be blitted onto the panel"

    # The last text_surf blit is the CC indicator; its x should be
    # in the right portion of the panel (panel_w = 8+160+4+20+8 = 200)
    cc_x, cc_y = cc_blits[-1].args[1]
    assert cc_x > 150, f"CC x={cc_x} should be in right side of 200px panel"
    assert cc_y < 16, f"CC y={cc_y} should be near top of panel"
