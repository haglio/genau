"""The pointer over the console Genau draws on top of its clip.

In genau mode Genau owns the main slot, so it draws Fun Time's console itself
and a press on that console has to reach Fun Time the way a press on the
dashboard would: as a command on the dashboard's own channel, routed like any
other.

Held together here rather than as four callbacks threaded from the composition
root, because they are one device: what the press took hold of is what the drag
goes on setting, and what letting go lets go of.

It presses the panel and the chip themselves, not the window they are drawn in:
the window has no say in where a press lands, and routing through it made the
view a hit-test switchboard for two surfaces it only paints.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from player_core.file_channel import append_command

from .clip_scrubber import ClipScrubber
from .console_panel import ConsolePanel
from .volume_chip import VolumeChip

# Fun Time's verb for the whole room's pause, spelled here as every verb this
# window asks for is.  A press on the clip is a press on the main player, and
# the pause it means is the room's -- Genau has none of its own to give.
OMNIPAUSE_TOGGLE = "omnipause_toggle"


class ConsolePointer:
    def __init__(self, console: ConsolePanel, volume: VolumeChip,
                 scrubber: ClipScrubber, *,
                 window, dashboard_cmd_file: Path, seek: Callable[[float], None]):
        self.console = console
        self.volume = volume
        self.scrubber = scrubber
        self.window = window
        self.dashboard_cmd_file = dashboard_cmd_file
        self.seek = seek
        self._seeking = False

    def _post(self, command: str) -> None:
        """Ask Fun Time for what the console just said."""
        if command:
            append_command(self.dashboard_cmd_file, command)

    def press(self, mx: int, my: int) -> None:
        """A press on what Genau draws over its clip — the volume chip, the
        clip's own bar, a console button's own command, the level the drive
        readout's bar under the pointer is set to, or, on the clip itself, the
        room's pause.

        The chip is tried first: it floats in its own corner, so a press on it is
        never also a press on the panel.
        """
        win_w, win_h = self.window.size
        press = self.volume.press_at(mx, my, win_w=win_w, win_h=win_h)
        if press is not None:
            # Shown first, asked for second: the chip is following the pointer
            # and Fun Time's answer is a tick away.
            self.volume.show(press.level, press.muted)
            self._post(press.command)
            return
        if self.scrubber.takes(my, win_h=win_h):
            self._seeking = True
            self.seek(self.scrubber.fraction_at(mx, win_w=win_w))
            return
        asked = self.console.press_at(mx, my)
        if not asked and not self.window.hud_active:
            # The clip is what this window shows, so the press is on the main
            # player.  In HUD mode it is the see-through layer over Nau instead:
            # the picture's own presses reach Nau through the color key, and
            # what arrives here landed on the HUD's opaque chrome.
            asked = OMNIPAUSE_TOGGLE
        self._post(asked)

    def drag(self, mx: int, my: int) -> None:
        """The pointer moving with the button down: a bar the press took hold of
        goes on being set, and says nothing while its level has not moved.  The
        clip's own bar goes on seeking, wherever the pointer has got to."""
        if self._seeking:
            self.seek(self.scrubber.fraction_at(mx, win_w=self.window.size[0]))
            return
        self._post(self.console.drag_to(mx, my))

    def release(self) -> None:
        self._seeking = False
        self.console.release()

    def motion(self, mx: int, my: int) -> None:
        self.console.hover_at(mx, my)
