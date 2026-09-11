"""A player in a session does not quit itself — it asks the session to quit.

Every gesture that ends one of these windows on its own — the close button, Alt+F4,
Ctrl+Q — ends only that window, and inside a Fun Time session that is wrong: the
sequencer put six windows up together and there is nothing to refill the gap one
leaving makes.  It bit for real.  Opt+Cmd+Q on a Mac keyboard arrives as Alt+F4,
so it closed the main player, then the portrait satellite, then the landscape one,
one press at a time, while the dashboard, Genau and the audio companion carried on
and the session had to be ended by voice.

The scan further down is what covers the run loop itself, which needs a real
window and so cannot be exercised here — the same reason
``test_focus_clickthrough`` reads its guarantee off the source.  Genau's loop
calls ``quit_gesture`` directly; the gesture itself is
``player_core.session_quit``'s and tested there.  Fun Time's main player and
satellites carry the same scan in their own repo.
"""
from __future__ import annotations

import ast
from pathlib import Path

from player_core.session_quit import SESSION_QUIT

REPO = Path(__file__).resolve().parents[1]
# Every loop that answers a quit gesture, and the call it answers it with.  The
# loading screen is not one: it runs before the session has a dispatch loop to
# ask, so giving up on the wait there is still this window's own business.
PLAYER_LOOPS = {
    REPO / "genau" / "lifecycle.py": "quit_gesture",
}


def test_the_ask_is_the_dashboards_own_quit_verb():
    """What the Quit button posts and the dispatch loop turns into the
    teardown.  Rename it and this player asks for something fun_time does
    not answer, so the gesture would go quiet instead of wrong."""
    assert SESSION_QUIT == "quit"


def _calls(source: Path, name: str) -> bool:
    """Whether *source* calls *name*, plainly or through something holding it."""
    tree = ast.parse(source.read_text(encoding="utf-8"))
    return any(
        isinstance(node, ast.Call) and (
            (isinstance(node.func, ast.Name) and node.func.id == name)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == name)
        )
        for node in ast.walk(tree)
    )


def test_every_player_loop_routes_its_quit_through_the_session():
    """A loop that sets its own stop event straight from a QUIT event is the
    regression: it looks right standalone and takes one window out of a session."""
    missing = [
        source.relative_to(REPO).as_posix()
        for source, call in PLAYER_LOOPS.items()
        if not _calls(source, call)
    ]

    assert not missing, f"these end themselves instead of asking the session: {missing}"
