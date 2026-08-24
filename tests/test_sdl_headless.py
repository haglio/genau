"""The suite must drive SDL through the dummy video driver.

Agents run this suite on every commit, on the machine that also runs the live
players.  A view built without the mock -- a fixture that stops reaching, a new
test that constructs the real thing -- puts a window on that screen; with the
dummy driver it puts nothing anywhere.  The merge gate exports
`SDL_VIDEODRIVER=dummy` for CI, which does nothing for the run an agent starts
by hand, so `tests/conftest.py` sets it too.  This asks SDL which driver it
actually chose rather than reading back the variable that asked for it.
"""
from __future__ import annotations

import pygame


def test_the_suite_drives_the_dummy_video_driver():
    pygame.display.init()
    try:
        assert pygame.display.get_driver() == "dummy"
    finally:
        pygame.display.quit()
