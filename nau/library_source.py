"""Standalone library source: discovered entries + durations + clips.

Bundles everything the length-mode toggle needs so startup and the runtime
switch build playlists from the same data. Fun Time drives its own explicit
playlist and does not use this.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

from .discovery import discover_entries
from .duration_cache import DurationCache
from .library import (
    FULL,
    SHORTS,
    LibraryEntry,
    group_versions,
    library_playlist,
    version_index_from_groups,
)

# The app starts in full-length mode; the toggle flips to shorts and back.
DEFAULT_MODE = FULL
OTHER_MODE = SHORTS


@dataclass(frozen=True)
class LibrarySource:
    entries: list[LibraryEntry]
    clips: list[LibraryEntry]
    durations: dict[Path, float]
    rng: random.Random
    # Nau is a general player standalone (funscript-focus is Fun Time's
    # F-mode job); versions/length filtering apply, but every video is served.
    scripted_only: bool = False

    def playlist_for(self, mode: str) -> list[tuple[Path, Path | None]]:
        return library_playlist(
            self.entries,
            mode=mode,
            durations=self.durations,
            clips=self.clips,
            rng=self.rng,
            scripted_only=self.scripted_only,
        )

    @property
    def version_index(self) -> dict[Path, list[tuple[Path, Path | None]]]:
        """Version-cycle map over every video (main entries and clips).

        Built from all discovered content, not just the active mode, so
        cycling versions works no matter which length mode is showing.
        """
        return version_index_from_groups(
            group_versions(self.entries + self.clips)
        )


def discover_clips(clips_dir: Path | None) -> list[LibraryEntry]:
    """Clip videos in *clips_dir* (unscripted, always treated as shorts)."""
    if clips_dir is None or not clips_dir.is_dir():
        return []
    from genau.video import SUPPORTED_VIDEO_EXTS

    clips: list[LibraryEntry] = []
    for path in sorted(clips_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in SUPPORTED_VIDEO_EXTS:
            clips.append(LibraryEntry(video=path, funscript=None, size=path.stat().st_size))
    return clips


def build_library_source(
    videos_dir: Path,
    scripts_dir: Path,
    clips_dir: Path | None,
    *,
    rng: random.Random,
    duration_cache: DurationCache | None = None,
    durations: dict[Path, float] | None = None,
    scripted_only: bool = False,
) -> LibrarySource:
    """Discover videos + clips and obtain the durations mode-filtering needs.

    Pass *durations* to supply them directly (tests); otherwise a
    *duration_cache* is probed (cached) and persisted.  *scripted_only*
    defaults False (Nau plays everything standalone); pass False to serve
    every video regardless of funscript.
    """
    entries = discover_entries(videos_dir, scripts_dir)
    clips = discover_clips(clips_dir)
    if durations is None:
        if duration_cache is None:
            raise ValueError("either durations or duration_cache must be given")
        durations = {e.video: duration_cache.duration_for(e.video) for e in entries}
        duration_cache.save()
    return LibrarySource(
        entries=entries, clips=clips, durations=durations, rng=rng,
        scripted_only=scripted_only,
    )
