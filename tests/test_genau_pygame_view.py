"""What Genau draws in its window: the clip, the loading line, and the two
surfaces genau mode puts on top of them.

The window is `test_genau_window.py`; the console and the chip answer for
themselves in `test_genau_console_pointer.py` and `test_genau_volume_chip.py`.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from player_core.console import ConsoleModel
from player_core.console_hud import ConsoleHud, hud_xy
from player_core.hud_placement import HudCorner

import genau.pygame_view as pv
from genau.clip_scrubber import ClipScrubber
from genau.console_panel import ConsolePanel
from genau.pygame_view import PygameView
from genau.volume_chip import VolumeChip


def _view(**geometry):
    """A view over its own console, chip and scrubber, the way the app builds one."""
    return PygameView(
        console=ConsolePanel(), volume=VolumeChip(), scrubber=ClipScrubber(), **geometry)


def test_hud_mode_defaults_to_false(mock_pygame):
    view = _view(width=800, height=600)

    assert view.hud_active is False


def test_present_scene_skips_texture_in_hud_mode(mock_pygame):
    view = _view(width=800, height=600)
    texture = MagicMock()
    view._current_texture = texture
    view.window.hud_active = True

    view._present_scene()

    texture.draw.assert_not_called()


def test_present_scene_draws_the_texture(mock_pygame):
    view = _view(width=800, height=600)
    view.window.window.size = (800, 600)
    texture = MagicMock()
    view._current_texture = texture
    view._video_size = (1920, 1080)
    view.window.hud_active = False

    view._present_scene()

    texture.draw.assert_called()


def test_present_scene_draws_texture_with_dstrect(mock_pygame):
    view = _view(width=800, height=600)
    view.window.window.size = (800, 600)
    texture = MagicMock()
    view._current_texture = texture
    view._video_size = (1920, 1080)
    view.window.hud_active = False

    view._present_scene()

    texture.draw.assert_called()
    # Every draw call must pass a dstrect (no bare .draw())
    for call in texture.draw.call_args_list:
        assert "dstrect" in call.kwargs

def test_present_scene_tiles_portrait_texture(mock_pygame):
    view = _view(width=1200, height=900)
    view.window.window.size = (1200, 900)
    texture = MagicMock()
    view._current_texture = texture
    view._video_size = (1080, 1920)  # portrait
    view.window.hud_active = False

    view._present_scene()

    assert texture.draw.call_count == 2


def test_hud_mode_leaves_the_console_to_main_player(mock_pygame):
    """HUD mode is kino mode: this window is a see-through layer over the main
    player's, and the main player draws the console there. Drawing it here as
    well would put the same panel on screen twice, and with the track, the
    frame count and the volume on that panel it would double those too."""
    view = _view(width=800, height=600)
    view.window.hud_active = True
    view._console.show(MagicMock())
    view._draw_console = MagicMock()

    view._present_scene()

    view._draw_console.assert_not_called()


def test_genau_draws_the_console_carrying_the_clips_row_when_it_owns_the_screen(
        mock_pygame):
    """One panel: the track, the frame count and the volume are a block of the
    console rather than three things drawn over the clip."""
    view = _view(width=800, height=600)
    view.window.hud_active = False
    view._console.show(MagicMock())
    view._console.show_row = MagicMock()
    view._draw_console = MagicMock()

    view._present_scene()

    view._draw_console.assert_called_once()
    view._console.show_row.assert_called_once_with(view._scrubber.row(
        view._volume.shown))


class TestTheLoadingLine:
    """`genau/tests/009`: deleting the two lines that draw it left every view
    test green, because they asserted that private methods had been called
    after monkeypatching those very methods onto the instance.  These ask the
    renderer what came out instead.
    """

    @staticmethod
    def _drawn(view, mock_pygame) -> bool:
        # The one thing the fake pygame cannot answer for itself: a rendered
        # line has a size, and the overlay lays itself out from it.
        mock_pygame.font.SysFont.return_value.render.return_value.get_size.return_value = (
            120, 20)
        pv.Texture.from_surface.reset_mock()
        view._present_scene()
        return pv.Texture.from_surface.return_value.draw.called

    def test_it_goes_over_the_clip_while_there_is_one_to_say(self, mock_pygame):
        view = _view(width=800, height=600)
        view.window.window.size = (800, 600)
        view._current_texture = MagicMock()

        view.set_loading_text("Reading the library")

        assert self._drawn(view, mock_pygame)

    def test_nothing_is_drawn_once_it_is_cleared(self, mock_pygame):
        view = _view(width=800, height=600)
        view.window.window.size = (800, 600)
        view._current_texture = MagicMock()
        view.set_loading_text("Reading the library")

        view.set_loading_text(None)

        assert not self._drawn(view, mock_pygame)

    def test_the_hud_layer_never_carries_it(self, mock_pygame):
        """HUD mode is kino mode: this window is a see-through layer over
        The main player's, and a line drawn here would float over the main player's video."""
        view = _view(width=800, height=600)
        view.window.window.size = (800, 600)
        view._current_texture = MagicMock()
        view.set_loading_text("Reading the library")
        view.window.hud_active = True

        assert not self._drawn(view, mock_pygame)


def _showing(view, corner: HudCorner) -> None:
    view.window.window.size = (800, 600)
    view.window.hud_active = False
    view._console.show(ConsoleHud(console=ConsoleModel(hud_corner=corner)))


def _blit(mock_pygame) -> tuple[tuple[int, int], tuple[int, int]]:
    """Where the console was blitted and how big it was."""
    at, size = mock_pygame.Rect.call_args.args
    return at, size


def test_the_console_is_drawn_in_the_corner_the_room_moved_it_to(mock_pygame):
    """The room can put the panel in any corner and a press has to land where it
    is drawn, so the blit follows the painter rather than the upper left."""
    view = _view(width=800, height=600)
    _showing(view, HudCorner.UPPER_RIGHT)

    view._draw_console()

    (left, top), (panel_w, _panel_h) = _blit(mock_pygame)
    assert left + panel_w == 800 - hud_xy()[0]
    assert top == hud_xy()[1]


def test_a_console_in_a_lower_corner_sits_against_the_windows_edge(mock_pygame):
    """The clip's track rides on the panel now, so nothing is drawn along the
    lower edge for a panel against it to clear."""
    view = _view(width=800, height=600)
    view._scrubber.follow(SimpleNamespace(
        current_frame_index=5, current_clip_entry=lambda: {"frames": [object()] * 20}))
    _showing(view, HudCorner.LOWER_LEFT)

    view._draw_console()

    (left, top), (_panel_w, panel_h) = _blit(mock_pygame)
    assert left == hud_xy()[0]
    assert top + panel_h == 600 - hud_xy()[1]
