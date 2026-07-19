"""The length mode Nau was last in, kept across sessions.

Fun Time resumes the playlist a session closed on rather than rebuilding it (it
rotates last session's file to the video that was on screen), so the videos Nau
opens with are last session's — chosen by last session's mode.  A list of files
does not say which mode chose it, so Nau writes the mode down and reads it back,
and the HUD can name a mode the playlist is really in instead of assuming the
default.
"""
from __future__ import annotations

from pathlib import Path

from .library_source import LENGTH_MODES


class ModeMemory:
    """Nau's last length mode, in a one-word file beside its duration cache."""

    def __init__(self, path: Path | None) -> None:
        self._path = path

    def read(self) -> str:
        """The remembered mode, or "" when there is nothing to remember.

        A word this build no longer knows reads as nothing: the file outlives
        the code that wrote it, and a mode the library cannot filter by would be
        a label over a playlist built some other way.
        """
        if self._path is None:
            return ""
        try:
            mode = self._path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
        return mode if mode in LENGTH_MODES else ""

    def write(self, mode: str) -> None:
        """Remember *mode*; a write that cannot land is simply not remembered."""
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(mode, encoding="utf-8")
        except OSError:
            pass
