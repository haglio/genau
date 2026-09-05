"""The channel this player asks Fun Time on, and what it does with no Fun Time.

Every control on Nau's HUD *asks* rather than acts — the console's buttons
because the verbs are the room's, not this player's, and the volume slider
because Fun Time holds the authority over the main slot's sound.  So they all
end up here, on the one file the dashboard's own buttons write to.

Quitting arrives on it too, which is why the gesture lives beside the asks
rather than with the window: in a session, closing this window means quitting
the session, and that is a verb like any other.  See :mod:`player_core.session_quit`
for why.

Lived as two closures inside ``nau.app``'s run loop, where the file was the
argparse namespace's and nothing could reach either one to test it.
"""
from __future__ import annotations

from pathlib import Path

from player_core.file_channel import append_command
from player_core.session_quit import quit_gesture


class Dashboard:
    """Fun Time's command channel, as one of its windows asks on it."""

    def __init__(self, cmd_file: Path) -> None:
        self._cmd_file = cmd_file

    def post(self, command: str) -> None:
        """Ask Fun Time for *command*.

        Appended, because that file carries every mouse- and voice-driven writer
        at once and the dispatch loop drains it a tick at a time.
        """
        append_command(self._cmd_file, command)

    def take_quit_gesture(self) -> None:
        """Answer a quit gesture on this player: the close box, Alt+F4, Ctrl+Q.

        It is the session that goes, not this player: the ask goes out and Nau
        stays up until the teardown reaches it, which is what puts the closing
        cover over all six windows instead of this one blinking out ahead of
        them.
        """
        quit_gesture(self._cmd_file)
