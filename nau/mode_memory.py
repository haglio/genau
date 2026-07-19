"""The mode Nau was last in, kept across sessions.

Fun Time resumes the playlist a session closed on rather than rebuilding it (it
rotates last session's file to the video that was on screen), so the videos Nau
opens with are last session's — chosen by last session's mode.  A list of files
does not say which mode chose it, so Nau writes the mode down and reads it back,
and the HUD can name a mode the playlist is really in instead of assuming the
default.

The compilation rides along for a stronger reason: entering one swaps Nau's
playlist *in memory only* — the file Fun Time resumes never sees it — so being
inside a compilation is remembered here or not at all.  The clip that was on
screen comes too, because it is the anchor the volume is rebuilt around: Fun
Time rotates the resumed playlist onto the video its player last showed, but
only when that video is *in* the file, and a compilation's clips often are not.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .library_source import LENGTH_MODES


@dataclass(frozen=True)
class RememberedMode:
    """What Nau was in when it last wrote itself down."""

    length_mode: str = ""
    compilation: str = ""
    video: str = ""


class ModeMemory:
    """Nau's mode in a small key=value file beside its duration cache."""

    def __init__(self, path: Path | None) -> None:
        self._path = path

    def read(self) -> RememberedMode:
        """What was remembered, with anything unrecognised left empty.

        A length mode this build no longer knows reads as nothing: the file
        outlives the code that wrote it, and a mode the library cannot filter by
        would be a label over a playlist built some other way.
        """
        fields = self._fields()
        length_mode = fields.get("length_mode", "")
        return RememberedMode(
            length_mode=length_mode if length_mode in LENGTH_MODES else "",
            compilation=fields.get("compilation", ""),
            video=fields.get("video", ""),
        )

    def write(self, mode: RememberedMode) -> None:
        """Remember *mode*; a write that cannot land is simply not remembered."""
        if self._path is None:
            return
        text = (f"length_mode={mode.length_mode}\ncompilation={mode.compilation}\n"
                f"video={mode.video}\n")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(text, encoding="utf-8")
        except OSError:
            pass

    def _fields(self) -> dict[str, str]:
        if self._path is None:
            return {}
        try:
            text = self._path.read_text(encoding="utf-8")
        except OSError:
            return {}
        # Split on the first "=" only: a compilation is titled for a shelf and
        # may carry anything but a newline.
        return dict(
            line.split("=", 1) for line in text.splitlines() if "=" in line
        )
