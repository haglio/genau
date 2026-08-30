"""What a player does when it is asked to quit and it is one window of a session.

Alone it is an application and the close button, Alt+F4 and Ctrl+Q end it.  In a
Fun Time session it is one of several windows the sequencer put up together, so
every one of those gestures means what it means on the dashboard's own window:
quit Fun Time.  The ask goes out on the dashboard's channel and the session comes
down as a whole, behind its closing cover, rather than this window blinking out
ahead of the rest.
"""
from __future__ import annotations

from pathlib import Path

from player_core.file_channel import append_command

# The verb fun_time's dashboard posts from its Quit button, and the one its
# dispatch loop turns into the teardown of every window in the session.
SESSION_QUIT = "quit"


def quit_gesture(dashboard_cmd_file: Path | None) -> bool:
    """Answer a quit gesture on this player.  True if this player should stop.

    A dashboard command file is what makes this a session: the ask goes out and
    this player keeps running until the teardown reaches it.  Without one there
    is nobody to ask, and the gesture ends this player.
    """
    if dashboard_cmd_file is None:
        return True
    append_command(dashboard_cmd_file, SESSION_QUIT)
    return False
