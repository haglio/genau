from __future__ import annotations

from player_core.console_hud import ConsoleHud, hud_xy

from genau.console_panel import ConsolePanel


def test_a_press_on_the_panel_it_draws_is_on_it():
    panel = ConsolePanel()
    panel.show(ConsoleHud())
    panel.rgba()

    assert panel.covers(*hud_xy())


def test_before_the_first_panel_there_is_nothing_under_a_press():
    """The engine composes one on its first tick and every tick after, so this
    is the only frame with none -- and a press in it must not land on the panel
    the painter has not drawn."""
    panel = ConsolePanel()

    assert panel.rgba() is None
    assert not panel.covers(*hud_xy())
