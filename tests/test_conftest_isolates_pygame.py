"""The view tests must be mocked whichever order the suite collects in.

`genau.pygame_view` binds `Window`/`Renderer`/`Texture` at import time, so a
fixture that swaps `sys.modules["pygame"]` reaches them only while that module
has never been imported.  Any test module importing `nau.app` first -- it pulls
the view in -- left those names as the real SDL ones, and the twenty-three view
tests behind the fixture went on to build real windows on the machine that also
runs the live players.  Alphabetical collection was the only thing standing
between the suite and that.

This file imports the view for real, before anything patches it, so the fixture
is always asked the hard question rather than the easy one.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import genau.pygame_view as pygame_view


def test_the_view_is_mocked_even_though_it_was_already_imported(mock_pygame):
    for name in ("Window", "Renderer", "Texture"):
        assert isinstance(getattr(pygame_view, name), MagicMock), (
            f"{name} is still the real SDL one -- a view built under this "
            "fixture opens a window instead of recording a call"
        )
    assert pygame_view.pygame is mock_pygame
