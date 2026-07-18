"""One-shot notices Nau raises for the Fun Time overlay.

Nau owns the library index, so only Nau can tell that "full video" or "money
shot" had nowhere to go. It has no text layer of its own, and Fun Time already
flashes notices over the primary display — so the result travels as a tiny
sequenced file: Nau bumps the sequence, Fun Time notices the change and flashes
the message once. A missed read just means a missed flash, never a stuck one.
"""
from __future__ import annotations

from pathlib import Path


class NoticeWriter:
    """Publishes Nau's latest one-shot notice to *path* (key=value lines)."""

    def __init__(self, path: Path | None) -> None:
        self._path = path
        self._seq = 0

    def say(self, message: str, *, level: str = "error") -> bool:
        """Raise *message*; ``level`` "error" flashes red, "notice" green."""
        if self._path is None:
            return False
        self._seq += 1
        text = f"seq={self._seq}\nlevel={level}\nmessage={message}\n"
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(text, encoding="utf-8")
        except OSError:
            return False
        return True

