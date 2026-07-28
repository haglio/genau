"""One-shot notices Nau raises for the Fun Time overlay.

Nau owns the library index, so only Nau can tell that "full video" or "money
shot" had nowhere to go. It has no text layer of its own, and Fun Time already
flashes notices over the primary display — so the result travels as a tiny
sequenced file: Nau bumps the sequence, Fun Time notices the change and flashes
the message once. A missed read just means a missed flash, never a stuck one.
"""
from __future__ import annotations

import time
from pathlib import Path


class NoticeWriter:
    """Publishes Nau's latest one-shot notice to *path* (key=value lines)."""

    def __init__(self, path: Path | None, *, clock=time.time) -> None:
        self._path = path
        self._clock = clock

    def say(self, message: str, *, level: str = "error") -> bool:
        """Raise *message*; ``level`` picks the colour Fun Time flashes it in.

        "error" is red, "notice" white, and "favorite" green — green being what
        Fun Time reserves for the favourites and the funscripts, so a funscript
        jump says so in the colour and an ordinary jump does not.

        The sequence is a wall-clock stamp rather than a counter. A counter
        restarts at 1 whenever Nau does, while the reader is still holding the
        high number from the previous session — so every notice of the new
        session read as older than what had already been shown, and none of
        them ever flashed.
        """
        if self._path is None:
            return False
        text = f"seq={self._clock():.3f}\nlevel={level}\nmessage={message}\n"
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(text, encoding="utf-8")
        except OSError:
            return False
        return True

