"""The view tests must be mocked whichever order the suite collects in.

`genau.window` binds `Window`/`Renderer` and `genau.pygame_view` binds
`Texture`, all at import time, so a fixture that swaps `sys.modules["pygame"]`
reaches them only while neither module has ever been imported.  Any test module
importing the view first -- `genau.app` pulls it in -- left those names as the
real SDL ones, and the view tests relying on the fixture went on to build real
windows on the machine that also runs the live players.  Alphabetical
collection was the only thing standing between the suite and that.

This file imports both for real, before anything patches them, so the fixture is
always asked the hard question rather than the easy one.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from genau import pygame_view, window

# Which module binds which SDL name, so a name that MOVES between them is a
# failure here rather than a real window on the machine.
BINDINGS = [(window, "Window"), (window, "Renderer"), (pygame_view, "Texture")]


@pytest.mark.parametrize("module, name", BINDINGS,
                         ids=lambda v: v if isinstance(v, str) else v.__name__)
def test_the_sdl_names_are_mocked_even_though_they_were_already_imported(
        module, name, mock_pygame):
    assert isinstance(getattr(module, name), MagicMock), (
        f"{module.__name__}.{name} is still the real SDL one -- a view built "
        "under this fixture opens a window instead of recording a call"
    )


def test_both_modules_hold_the_fake_pygame(mock_pygame):
    assert pygame_view.pygame is mock_pygame
    assert window.pygame is mock_pygame
