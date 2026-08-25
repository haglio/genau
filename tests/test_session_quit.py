"""A player in a session does not quit itself — it asks the session to quit.

Every gesture that ends one of these windows on its own — the close box, Alt+F4,
Ctrl+Q — ends only that window, and inside a Fun Time session that is wrong: the
sequencer put six windows up together and there is nothing to refill the hole one
leaving makes.  It bit for real.  Opt+Cmd+Q on a Mac keyboard arrives as Alt+F4,
so it closed Nau, then the portrait satellite, then the landscape one, one press
at a time, while the dashboard, Genau and the audio companion carried on and the
session had to be ended by voice.

The scan at the bottom is what covers the run loops themselves, which need a real
window and the libmpv DLL and so cannot be exercised here — the same reason
``test_focus_clickthrough`` reads its guarantee off the source.  What each loop
routes *through* differs: Nau's gesture is answered by ``nau.dashboard``, which
has its own tests in ``test_nau_dashboard``; Genau's calls ``quit_gesture``
directly.  Either way the regression is the same, and it is the call the loop
makes that the scan is about.
"""
from __future__ import annotations

import ast
from pathlib import Path

from genau.session_quit import SESSION_QUIT, quit_gesture

REPO = Path(__file__).resolve().parents[1]
# Every loop that answers a quit gesture, and the call it answers it with.  The
# loading screen is not one: it runs before the session has a dispatch loop to
# ask, so giving up on the wait there is still this window's own business.
PLAYER_LOOPS = {
    REPO / "nau" / "app.py": "take_quit_gesture",
    REPO / "genau" / "lifecycle.py": "quit_gesture",
}


class TestQuitGesture:
    def test_in_a_session_it_asks_and_this_player_stays(self, tmp_path: Path):
        cmd_file = tmp_path / "dashboard_cmd.txt"

        assert quit_gesture(cmd_file) is False
        assert cmd_file.read_text(encoding="utf-8").split() == [SESSION_QUIT]

    def test_the_ask_is_the_dashboards_own_quit_verb(self):
        """What the Quit button posts and the dispatch loop turns into the
        teardown.  Rename it here and this player asks for something fun_time
        does not answer, so the gesture would go quiet instead of wrong."""
        assert SESSION_QUIT == "quit"

    def test_it_joins_the_queue_rather_than_replacing_it(self, tmp_path: Path):
        """The channel carries every writer at once and is drained a tick at a
        time, so an ask that overwrote it would drop whatever was waiting."""
        cmd_file = tmp_path / "dashboard_cmd.txt"
        cmd_file.write_text("main_next\n", encoding="utf-8")

        quit_gesture(cmd_file)

        assert cmd_file.read_text(encoding="utf-8").split() == ["main_next", SESSION_QUIT]

    def test_standalone_the_gesture_ends_this_player(self):
        """No dashboard is what standalone means: there is nobody to ask, and
        closing the window is exactly what the user asked for."""
        assert quit_gesture(None) is True


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
