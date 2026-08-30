"""The pointer over the console Genau draws on top of its clip.

In genau mode Genau owns the main slot, so it draws Fun Time's console itself
and a press on that console has to reach Fun Time the way a press on the
dashboard would: as a command on the dashboard's own channel, routed like any
other.  Standalone there is no dashboard and nowhere to ask, so the same presses
are inert rather than an error.

Held together here rather than as four callbacks threaded from the composition
root, because they are one device: what the press took hold of is what the drag
goes on setting, and what letting go lets go of.
"""
from __future__ import annotations

from pathlib import Path

from player_core.file_channel import append_command


class ConsolePointer:
    def __init__(self, view, dashboard_cmd_file: Path | None = None):
        self.view = view
        self.dashboard_cmd_file = dashboard_cmd_file

    def _post(self, command: str) -> None:
        """Ask Fun Time for what the console just said.  Inert with no dashboard."""
        if command and self.dashboard_cmd_file is not None:
            append_command(self.dashboard_cmd_file, command)

    def press(self, mx: int, my: int) -> None:
        """A press on what Genau draws over its clip — the volume chip, a console
        button's own command, or the level the drive readout's bar under the
        pointer is set to.

        The chip is tried first: it floats in its own corner, so a press on it is
        never also a press on the panel.
        """
        volume = self.view.volume_press_at(mx, my)
        if volume is not None:
            # Shown first, asked for second: the chip is following the pointer
            # and Fun Time's answer is a tick away.
            self.view.set_volume(volume.level, volume.muted)
            self._post(volume.command)
            return
        self._post(self.view.console_press_at(mx, my))

    def drag(self, mx: int, my: int) -> None:
        """The pointer moving with the button down: a bar the press took hold of
        goes on being set, and says nothing while its level has not moved."""
        self._post(self.view.console_drag_to(mx, my))

    def release(self) -> None:
        self.view.console_release()

    def motion(self, mx: int, my: int) -> None:
        self.view.set_console_hover(mx, my)
