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


def test_pygame_view_create(mock_pygame):
    from genau.pygame_view import PygameView

    view = PygameView(width=800, height=600, x=100, y=50, title="Genau")

    assert view.width == 800
    assert view.height == 600


def test_hud_mode_defaults_to_false(mock_pygame):
    from genau.pygame_view import PygameView

    view = PygameView(width=800, height=600)

    assert view.hud_active is False


def test_present_scene_skips_texture_in_hud_mode(mock_pygame):
    from genau.pygame_view import PygameView

    view = PygameView(width=800, height=600)
    texture = MagicMock()
    view._current_texture = texture
    view.hud_active = True

    view._present_scene()

    texture.draw.assert_not_called()


def test_present_scene_draws_texture_with_dstrect(mock_pygame):
    from genau.pygame_view import PygameView

    view = PygameView(width=800, height=600)
    view.window.size = (800, 600)
    texture = MagicMock()
    view._current_texture = texture
    view._video_size = (1920, 1080)
    view.hud_active = False

    view._present_scene()

    texture.draw.assert_called()
    # Every draw call must pass a dstrect (no bare .draw())
    for call in texture.draw.call_args_list:
        assert "dstrect" in call.kwargs

def test_present_scene_tiles_portrait_texture(mock_pygame):
    from genau.pygame_view import PygameView

    view = PygameView(width=1200, height=900)
    view.window.size = (1200, 900)
    texture = MagicMock()
    view._current_texture = texture
    view._video_size = (1080, 1920)  # portrait
    view.hud_active = False

    view._present_scene()

    assert texture.draw.call_count == 2


def test_present_scene_calls_draw_overlay_in_hud_mode(mock_pygame):
    from genau.pygame_view import PygameView

    view = PygameView(width=800, height=600)
    view.hud_active = True
    view._direct_overlay = MagicMock()  # non-None triggers overlay
    view._draw_direct_overlay = MagicMock()

    view._present_scene()

    view._draw_direct_overlay.assert_called_once()


def test_set_hud_mode_true_enables_layered_window(mock_pygame):
    from genau.pygame_view import PygameView

    view = PygameView(width=800, height=600)
    mock_user32 = MagicMock()
    mock_user32.GetWindowLongW.return_value = 0
    view._apply_layered_window = MagicMock()

    view.set_hud_mode(True)

    assert view.hud_active is True
    view._apply_layered_window.assert_called_once_with(True)


def test_set_hud_mode_false_removes_layered_window(mock_pygame):
    from genau.pygame_view import PygameView

    view = PygameView(width=800, height=600)
    view.hud_active = True
    view._apply_layered_window = MagicMock()

    view.set_hud_mode(False)

    assert view.hud_active is False
    view._apply_layered_window.assert_called_once_with(False)


def test_set_hud_mode_noop_when_already_in_requested_state(mock_pygame):
    from genau.pygame_view import PygameView

    view = PygameView(width=800, height=600)
    view._apply_layered_window = MagicMock()

    view.set_hud_mode(False)  # already False

    view._apply_layered_window.assert_not_called()
