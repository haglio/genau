from __future__ import annotations

from player_core.console_hud import ConsoleHud, hud_xy

from genau.console_panel import ConsolePanel


def test_a_press_on_the_panel_it_draws_is_on_it():
    panel = ConsolePanel()
    panel.show(ConsoleHud())
    panel.rgba()

    assert panel.covers(*hud_xy())


def test_a_panel_taken_down_is_under_no_press():
    panel = ConsolePanel()
    panel.show(ConsoleHud())
    panel.rgba()

    panel.show(None)

    assert not panel.covers(*hud_xy())
