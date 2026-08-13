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


def test_borderless_fills_the_whole_rect(mock_pygame):
    """Under Fun Time the window has no title bar — the mode it used to name is on
    the HUD — so it is chromeless and its client area is the whole rect, both to
    reclaim the space and to keep the Hybrid layer aligned with Nau's video."""
    import genau.pygame_view as pv

    pv.PygameView(width=800, height=600, x=100, y=50, title="Genau", borderless=True)

    _title, kwargs = pv.Window.call_args
    assert kwargs["size"] == (800, 600)   # the whole rect, no chrome subtracted
    assert kwargs["borderless"] is True
    assert pv.Window.return_value.position == (100, 50)  # the rect's own corner


def test_standalone_keeps_its_chrome(mock_pygame):
    """Run on its own (the default), the window keeps a title bar so it can be
    dragged and closed — the client is sized down to leave the video in the rect."""
    import genau.pygame_view as pv

    with patch.object(pv, "get_window_chrome_height", return_value=31):
        pv.PygameView(width=800, height=600, x=100, y=50, title="Genau")

    _title, kwargs = pv.Window.call_args
    assert kwargs["size"] == (800, 600 - 31)          # room left for the chrome
    assert kwargs.get("borderless", False) is False
    assert pv.Window.return_value.position == (100, 50 + 31)


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


def test_blank_defaults_to_false(mock_pygame):
    from genau.pygame_view import PygameView

    view = PygameView(width=800, height=600)

    assert view._blank is False


def test_present_scene_skips_texture_when_blank(mock_pygame):
    from genau.pygame_view import PygameView

    view = PygameView(width=800, height=600)
    view.window.size = (800, 600)
    texture = MagicMock()
    view._current_texture = texture
    view._video_size = (1920, 1080)
    view.hud_active = False
    view.set_blank(True)

    view._present_scene()

    texture.draw.assert_not_called()


def test_present_scene_skips_the_console_when_blank(mock_pygame):
    from genau.pygame_view import PygameView

    view = PygameView(width=800, height=600)
    view.hud_active = False
    view._console = MagicMock()  # non-None would normally trigger a draw
    view._draw_console = MagicMock()
    view.set_blank(True)

    view._present_scene()

    view._draw_console.assert_not_called()


def test_present_scene_clears_to_black_when_blank(mock_pygame):
    from genau.pygame_view import PygameView

    view = PygameView(width=800, height=600)
    view.hud_active = False
    view.set_blank(True)

    view._present_scene()

    assert view.renderer.draw_color == (0, 0, 0, 255)
    view.renderer.clear.assert_called()
    view.renderer.present.assert_called()


def test_present_scene_draws_texture_when_not_blank(mock_pygame):
    from genau.pygame_view import PygameView

    view = PygameView(width=800, height=600)
    view.window.size = (800, 600)
    texture = MagicMock()
    view._current_texture = texture
    view._video_size = (1920, 1080)
    view.hud_active = False
    view.set_blank(False)

    view._present_scene()

    texture.draw.assert_called()


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


def test_hud_mode_leaves_the_console_and_the_volume_to_nau(mock_pygame):
    """HUD mode is Hybrid: this window is a transparent layer over Nau's, and the
    readout is drawn inside Nau's console beneath the controls that move it.
    Drawing it here as well would put the same panel on screen twice — and the
    same goes for the volume chip, where two sliders would disagree about which
    press the level came from."""
    from genau.pygame_view import PygameView

    view = PygameView(width=800, height=600)
    view.hud_active = True
    view._console = MagicMock()
    view._draw_console = MagicMock()
    view._draw_volume = MagicMock()

    view._present_scene()

    view._draw_console.assert_not_called()
    view._draw_volume.assert_not_called()


def test_genau_draws_the_console_and_the_volume_when_it_owns_the_screen(mock_pygame):
    from genau.pygame_view import PygameView

    view = PygameView(width=800, height=600)
    view.hud_active = False
    view._console = MagicMock()
    view._draw_console = MagicMock()
    view._draw_volume = MagicMock()

    view._present_scene()

    view._draw_console.assert_called_once()
    view._draw_volume.assert_called_once()


def test_the_volume_chip_sits_where_naus_does_with_no_timeline_under_it(mock_pygame):
    """Genau's window IS the primary display in genau mode, so reaching for the
    sound must not mean finding the control somewhere else than in Nau's modes.
    Measured against the row Nau draws it in rather than against Genau's own call,
    which is what a chip nine pixels above Nau's still passed."""
    from player_core.timeline import TIMELINE_HEIGHT
    from player_core.volume import CHIP_H, CHIP_W, chip_xy
    from genau.pygame_view import PygameView

    view = PygameView(width=800, height=600)
    view.window.size = (800, 600)
    mock_pygame.Rect.reset_mock()

    view._draw_volume()

    nau_x, nau_y = chip_xy(win_w=800, win_h=600, timeline_h=TIMELINE_HEIGHT)
    assert mock_pygame.Rect.call_args.args == (nau_x, nau_y, CHIP_W, CHIP_H)


def test_a_press_on_the_chip_asks_fun_time_and_shows_the_new_level_at_once(mock_pygame):
    """Fun Time owns the level, so the press is a request — but its answer is a
    tick away, and a slider that waited for it would drag a frame behind the
    pointer.  The speaker end asks for the mute instead."""
    from player_core.volume import CHIP_W, VolumeHud, chip_xy
    from genau.pygame_view import PygameView

    view = PygameView(width=800, height=600)
    view.window.size = (800, 600)
    view.set_volume(30, False)
    vx, vy = chip_xy(win_w=800, win_h=600, timeline_h=0)

    assert view.press_volume_at(vx + CHIP_W - 2, vy + 10) == "audio_set_volume|100"
    assert view._volume == VolumeHud(volume=100, muted=False)

    assert view.press_volume_at(vx + 3, vy + 10) == "audio_mute"
    assert view._volume == VolumeHud(volume=100, muted=True)
    assert view.press_volume_at(vx + 3, vy + 10) == "audio_unmute"

    # A press nowhere near it asks for nothing, so the console behind gets it.
    assert view.press_volume_at(10, 10) == ""


def test_the_published_level_is_what_the_chip_shows(mock_pygame):
    """Genau neither owns the level nor plays the sound — a companion process
    carries the clip music — so what it draws is whatever Fun Time last said."""
    from player_core.volume import VolumeHud
    from genau.pygame_view import PygameView

    view = PygameView(width=800, height=600)

    view.set_volume(45, True)

    assert view._volume == VolumeHud(volume=45, muted=True)


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


def test_hud_window_identity_hybrid_when_active_else_base(mock_pygame):
    from pathlib import Path

    from genau.pygame_view import hud_window_identity

    args = dict(base_title="Genau", base_icon=Path("g.ico"),
                hybrid_title="Hybrid Nau+Genau", hybrid_icon=Path("h.ico"))
    assert hud_window_identity(True, **args) == ("Hybrid Nau+Genau", Path("h.ico"))
    assert hud_window_identity(False, **args) == ("Genau", Path("g.ico"))


def test_hud_window_identity_stays_genau_without_a_hybrid_identity(mock_pygame):
    from genau.pygame_view import hud_window_identity

    assert hud_window_identity(
        True, base_title="Genau", base_icon=None, hybrid_title=None, hybrid_icon=None
    ) == ("Genau", None)


def test_set_hud_mode_swaps_window_title_to_hybrid_and_back(mock_pygame, tmp_path):
    from genau.pygame_view import PygameView

    view = PygameView(
        width=800, height=600, title="Genau",
        hybrid_title="Hybrid Nau+Genau", hybrid_icon_path=tmp_path / "h.ico",
    )
    view._apply_layered_window = MagicMock()

    view.set_hud_mode(True)
    assert view.window.title == "Hybrid Nau+Genau"

    view.set_hud_mode(False)
    assert view.window.title == "Genau"
