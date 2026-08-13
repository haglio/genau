"""What a player does when it is asked to quit and it is one window of a session.

A player of this family runs two ways.  Alone, it is an application: the close
button, Alt+F4 and Ctrl+Q all end it, because ending it is what the user asked
for.  Placed in a Fun Time session it is not an application at all — it is one
of several windows the sequencer put on the screen together, driven from a
dashboard, and quitting it on its own leaves the session running around a hole
nothing refills.

So in a session every one of those gestures means the same thing it means on the
dashboard's own window: quit Fun Time.  It is asked for on the channel the
dashboard uses, and the session comes down as a whole, behind its closing cover,
the way it does from the Quit button or a spoken "quit".
"""
from __future__ import annotations

from pathlib import Path

from player_core.file_channel import append_command

# The verb fun_time's dashboard posts from its Quit button, and the one its
# dispatch loop turns into the teardown of every window in the session.
SESSION_QUIT = "quit"


def quit_gesture(dashboard_cmd_file: Path | None) -> bool:
    """Answer a quit gesture on this player.  True if this player should stop.

    With a dashboard command file there is a session to ask, so the ask goes out
    and this player keeps running: it is not its own to end, and it stays on
    screen until the teardown reaches it — which is what puts the closing cover
    up over all six windows instead of this one blinking out ahead of them.

    Without one there is nobody to ask, which is what standalone means, and the
    gesture ends this player as it always did.
    """
    if dashboard_cmd_file is None:
        return True
    append_command(dashboard_cmd_file, SESSION_QUIT)
    return False
