from __future__ import annotations

from pathlib import Path


class ClipSequenceController:
    def __init__(self, clips: list[Path]):
        if not clips:
            raise ValueError("ClipSequenceController requires at least one clip")
        self._clips = list(clips)
        self._index = 0

    @property
    def count(self) -> int:
        return len(self._clips)

    @property
    def current_number(self) -> int:
        return self._index + 1

    @property
    def current_path(self) -> Path:
        return self._clips[self._index]

    def step(self, delta: int) -> Path:
        self._index = (self._index + delta) % len(self._clips)
        return self.current_path

    def drop_current(self) -> Path | None:
        """Remove the current clip and return whichever one takes its place.

        Returns None — and keeps the clip — when it is the only one left,
        since a sequence with nothing in it has no frame to show.
        """
        if len(self._clips) <= 1:
            return None
        del self._clips[self._index]
        self._index %= len(self._clips)
        return self.current_path

    def nearby_candidates(self) -> list[Path]:
        if len(self._clips) <= 1:
            return []
        return [self._clips[(self._index + delta) % len(self._clips)] for delta in (1, -1)]
