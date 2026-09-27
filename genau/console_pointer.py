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
from player_core.hud_row import MUTE, SCRUBBER, VOLUME, row_part, volume_to

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
        # Which part of the clip's row a press is holding, so the track and
        # the slider can be dragged along and not only clicked.
        self._holding = ""

    def _post(self, command: str) -> None:
        """Ask Fun Time for what the console just said."""
        if command:
            append_command(self.dashboard_cmd_file, command)

    def press(self, mx: int, my: int) -> None:
        """A press on what Genau draws over its clip — the clip's row at the
        foot of the console, a console button's own command, the level the
        drive readout's bar under the pointer is set to, or, on the clip
        itself, the room's pause.

        The row is tried first: it is a block of the panel, so a press on it
        would otherwise be swallowed as a press on the panel's own chrome.
        """
        if self._press_row(mx, my):
            return
        asked = self.console.press_at(mx, my)
        if not asked and not self.window.hud_active and not self.console.covers(mx, my):
            # The clip is what this window shows, so the press is on the main
            # player.  In HUD mode it is the see-through layer over the main player instead:
            # the picture's own presses reach the main player through the color key, and
            # what arrives here landed on the HUD's opaque chrome.
            asked = OMNIPAUSE_TOGGLE
        self._post(asked)

    def _press_row(self, mx: int, my: int) -> bool:
        """A press on the clip's row: run the clip to that point, set the
        level, or flip the mute.  False if it missed the row.

        Hit-tested in the row's own coordinates, the way every panel that
        hosts that row does (:func:`player_core.hud_row.row_part`).
        """
        rect = self.console.row_rect
        if rect is None:
            return False
        x, y, width, height = rect
        px, py = mx - x, my - y
        if not (0 <= px < width and 0 <= py < height):
            return False
        self._holding = row_part(px, py, width=width)
        self._act_on_the_row(px, py, width)
        return True

    def _act_on_the_row(self, px: int, py: int, width: int) -> None:
        if self._holding == SCRUBBER:
            self.seek(self.scrubber.fraction_at(px, width=width))
        elif self._holding in (VOLUME, MUTE):
            press = (self.volume.pressed_the_speaker() if self._holding == MUTE
                     else self.volume.pressed_the_slider(
                         volume_to(px, py, width=width)))
            # Shown first, asked for second: the chip is following the pointer
            # and Fun Time's answer is a tick away.
            self.volume.show(press.level, press.muted)
            self._post(press.command)

    def drag(self, mx: int, my: int) -> None:
        """The pointer moving with the button down: a bar the press took hold of
        goes on being set, and says nothing while its level has not moved.  The
        clip's own track and the slider beside it go on being set too, wherever
        the pointer has got to -- but not the speaker, which is a press, so a
        pointer crossing it on its way along the slider does not flip it."""
        if self._holding in (SCRUBBER, VOLUME):
            rect = self.console.row_rect
            if rect is not None:
                self._act_on_the_row(mx - rect[0], my - rect[1], rect[2])
            return
        self._post(self.console.drag_to(mx, my))

    def release(self) -> None:
        self._holding = ""
        self.console.release()

    def motion(self, mx: int, my: int) -> None:
        self.console.hover_at(mx, my)
