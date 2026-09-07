"""What Genau draws in its window: the clip, the loading line, and the two
surfaces genau mode puts on top of them.

The window is `test_genau_window.py`; the console and the chip answer for
themselves in `test_genau_console_pointer.py` and `test_genau_volume_chip.py`.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from genau.clip_scrubber import ClipScrubber
from genau.console_panel import ConsolePanel
from genau.volume_chip import VolumeChip


def _view(**geometry):
    """A view over its own console, chip and scrubber, the way the app builds one."""
    from genau.pygame_view import PygameView

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


def test_hud_mode_leaves_the_console_and_the_volume_to_nau(mock_pygame):
    """HUD mode is video mode: this window is a see-through layer over Nau's, and the
    readout is drawn inside Nau's console beneath the controls that move it.
    Drawing it here as well would put the same panel on screen twice — and the
    same goes for the volume chip, where two sliders would disagree about which
    press the level came from."""
    view = _view(width=800, height=600)
    view.window.hud_active = True
    view._console.show(MagicMock())
    view._draw_console = MagicMock()
    view._draw_volume = MagicMock()

    view._present_scene()

    view._draw_console.assert_not_called()
    view._draw_volume.assert_not_called()


def test_genau_draws_the_console_the_scrubber_and_the_volume_when_it_owns_the_screen(
        mock_pygame):
    view = _view(width=800, height=600)
    view.window.hud_active = False
    view._console.show(MagicMock())
    view._draw_console = MagicMock()
    view._draw_scrubber = MagicMock()
    view._draw_volume = MagicMock()

    view._present_scene()

    view._draw_console.assert_called_once()
    view._draw_scrubber.assert_called_once()
    view._draw_volume.assert_called_once()


class TestTheLoadingLine:
    """`genau/tests/009`: deleting the two lines that draw it left every view
    test green, because they asserted that private methods had been called
    after monkeypatching those very methods onto the instance.  These ask the
    renderer what came out instead.
    """

    @staticmethod
    def _drawn(view, mock_pygame) -> bool:
        import genau.pygame_view as pv

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
        """HUD mode is video mode: this window is a see-through layer over
        Nau's, and a line drawn here would float over Nau's video."""
        view = _view(width=800, height=600)
        view.window.window.size = (800, 600)
        view._current_texture = MagicMock()
        view.set_loading_text("Reading the library")
        view.window.hud_active = True

        assert not self._drawn(view, mock_pygame)
