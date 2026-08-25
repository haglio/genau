"""What the room around this player says, kept between frames.

Two files arrive published by somebody else: the console panel Fun Time writes
about the main slot, and the readout Genau writes about what it is doing to the
device.  Both are replaced while this polls them, so a lost race reads a torn
file — and the readers answer None for that, meaning *keep what you have*.
Blanking either for a frame is a visible flicker on a HUD that redraws at 60fps.

Standalone there is neither file.  The console still draws, with the player's own
controls and nothing claimed about the room around it, and there is nothing
publishing a stroke at all.

Lived as two locals rebound inside ``nau.app``'s run loop, so the rule that keeps
them — the ``or`` on each read — had no test.
"""
from __future__ import annotations

from pathlib import Path

from player_core.console import ConsoleModel, genau_drives, read_console
from player_core.drive_readout import DriveHud, read_drive


class Published:
    """The last whole console and stroke this player managed to read."""

    def __init__(self, console_file: Path | None, drive_file: Path | None) -> None:
        self._console_file = console_file
        self._drive_file = drive_file
        self._console = ConsoleModel()
        self._drive: DriveHud | None = None

    @property
    def console(self) -> ConsoleModel:
        """What Fun Time last said about the main slot."""
        return self._console

    @property
    def drive(self) -> DriveHud | None:
        """Genau's own readout as it last published it, or None where nothing
        has published one — which is every frame of Nau's own mode."""
        return self._drive

    @property
    def genau_drives(self) -> bool:
        """Whether Genau is behind the screen and holding the device."""
        return genau_drives(self._console.mode)

    def refresh(self) -> None:
        """Read this frame's files, keeping whatever comes back torn.

        The stroke is read only while Genau is the one driving: in every other
        mode the file on disk is last session's, or another player's, and the
        picture would draw a stroke nobody is making.
        """
        if self._console_file is not None:
            self._console = read_console(self._console_file) or self._console
        if self._drive_file is not None and self.genau_drives:
            self._drive = read_drive(self._drive_file) or self._drive
