"""The window itself: the rect it claims, what it is called, and who can see
through it.  What is drawn inside it is `test_genau_pygame_view.py`.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from genau.window import GenauWindow, hud_window_identity


def test_it_claims_the_whole_rect_with_no_chrome(mock_pygame):
    """The window has no title bar — the mode it used to name is on the HUD — so
    it is chromeless and its client area is the whole rect, both to reclaim the
    space and to keep the video-mode layer aligned with Nau's video."""
    import genau.window as gw

    window = GenauWindow(width=800, height=600, x=100, y=50, title="Genau")

    _title, kwargs = gw.Window.call_args
    assert kwargs["size"] == (800, 600)   # the whole rect, no chrome subtracted
    assert kwargs["borderless"] is True
    assert gw.Window.return_value.position == (100, 50)  # the rect's own corner
    assert (window.width, window.height) == (800, 600)
    mock_pygame.init.assert_called_once()


def test_its_size_is_the_one_sdl_reports_rather_than_the_one_asked_for(mock_pygame):
    """Fun Time resizes this window under the app, so the rect it was made with
    is only ever the opening one."""
    window = GenauWindow(width=800, height=600)
    window.window.size = (1200, 900)

    assert window.size == (1200, 900)


def test_the_hud_is_off_until_something_turns_it_on(mock_pygame):
    assert GenauWindow(width=800, height=600).hud_active is False


def test_turning_the_hud_on_lets_the_desktop_through(mock_pygame):
    window = GenauWindow(width=800, height=600)
    window._layered = MagicMock()

    window.set_hud_mode(True)

    assert window.hud_active is True
    window._layered.set_transparent.assert_called_once_with(True)


def test_turning_it_off_makes_the_window_solid_again(mock_pygame):
    window = GenauWindow(width=800, height=600)
    window.set_hud_mode(True)
    window._layered = MagicMock()

    window.set_hud_mode(False)

    assert window.hud_active is False
    window._layered.set_transparent.assert_called_once_with(False)


def test_asking_for_the_state_it_is_already_in_asks_windows_nothing(mock_pygame):
    window = GenauWindow(width=800, height=600)
    window._layered = MagicMock()

    window.set_hud_mode(False)  # already False

    window._layered.set_transparent.assert_not_called()


def test_the_transparency_holds_the_handle_it_took_when_the_window_was_made(mock_pygame):
    """Not one looked up afterwards: the HUD renames this window, and fun_time
    separately finds it by caption substring, so a handle resolved after the
    rename is resolved against a caption that had just changed."""
    window = GenauWindow(width=800, height=600, title="Genau",
                         video_title="Video Nau+Genau")
    window._layered = MagicMock()
    window._layered.hwnd = 0x1234

    window.set_hud_mode(True)

    assert window.window.title == "Video Nau+Genau"
    assert window._layered.hwnd == 0x1234


def test_the_caption_swaps_to_the_video_one_and_back(mock_pygame):
    window = GenauWindow(width=800, height=600, title="Genau",
                         video_title="Video Nau+Genau")
    window._layered = MagicMock()

    window.set_hud_mode(True)
    assert window.window.title == "Video Nau+Genau"

    window.set_hud_mode(False)
    assert window.window.title == "Genau"


def test_the_identity_is_the_video_caption_when_active_else_the_base():
    args = dict(base_title="Genau", video_title="Video Nau+Genau")
    assert hud_window_identity(True, **args) == "Video Nau+Genau"
    assert hud_window_identity(False, **args) == "Genau"


def test_without_a_video_caption_it_stays_genau():
    assert hud_window_identity(True, base_title="Genau", video_title=None) == "Genau"
