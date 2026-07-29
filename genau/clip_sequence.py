from __future__ import annotations

from pathlib import Path


def _index_of(clips: list[Path], wanted: Path | None) -> int:
    """Where *wanted* sits in *clips*, or 0 for "not among them".

    Compared case-insensitively: the path comes back through a status file
    another process wrote, and Windows hands the same file back in either case.
    """
    if wanted is None:
        return 0
    key = str(wanted).lower()
    for index, clip in enumerate(clips):
        if str(clip).lower() == key:
            return index
    return 0


class ClipSequenceController:
    def __init__(self, clips: list[Path], *, start_at: Path | None = None):
        """*start_at* is the clip to open on — where a reopened session picks up.

        Only the clip, never an order: the folder is rescanned every launch and
        reshuffled when that is on, so the sequence around it is this session's
        own.  A clip that is no longer in it (deleted, or condemned as weird
        since) simply is not found, and the scan order stands from its top.
        """
        if not clips:
            raise ValueError("ClipSequenceController requires at least one clip")
        self._clips = list(clips)
        self._index = _index_of(self._clips, start_at)

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
