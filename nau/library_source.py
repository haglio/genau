"""Standalone library source: discovered entries + durations + clips.

Bundles everything the length-mode toggle needs so startup and the runtime
switch build playlists from the same data. Fun Time drives its own explicit
playlist and does not use this.
"""
from __future__ import annotations

import json
import random
from collections.abc import Callable
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


def read_version_group(video: Path, metadata_root: Path) -> str | None:
    """The version-family id Evolver recorded for *video*, or None.

    The metadata tree mirrors the video library one-to-one, so the sidecar sits
    at the same path under *metadata_root* as the clip sits under the library
    root — the ``videos`` sibling of *metadata_root* (``…/videos/metadata`` pairs
    with ``…/videos/videos``). A missing or malformed sidecar returns None, so
    the clip falls back to name-based grouping.
    """
    library_root = metadata_root.parent / "videos"
    try:
        rel = video.relative_to(library_root)
    except ValueError:
        return None
    sidecar = (metadata_root / rel).with_suffix(".json")
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    version = payload.get("version") if isinstance(payload, dict) else None
    if not isinstance(version, dict):
        return None
    group = version.get("group")
    return str(group) if group else None

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
    # When set, version families come from Evolver's metadata sidecars (the
    # authoritative record) instead of Nau's own name-prefix guess.
    metadata_root: Path | None = None

    def playlist_for(self, mode: str) -> list[tuple[Path, Path | None]]:
        return library_playlist(
            self.entries,
            mode=mode,
            durations=self.durations,
            clips=self.clips,
            rng=self.rng,
            scripted_only=self.scripted_only,
        )

    def _group_id_of(self) -> Callable[[Path], str | None] | None:
        if self.metadata_root is None:
            return None
        metadata_root = self.metadata_root
        return lambda video: read_version_group(video, metadata_root)

    @property
    def version_index(self) -> dict[Path, list[tuple[Path, Path | None]]]:
        """Version-cycle map over every video (main entries and clips).

        Built from all discovered content, not just the active mode, so
        cycling versions works no matter which length mode is showing.  Uses
        the metadata sidecars when a *metadata_root* is set, else names.
        """
        return version_index_from_groups(
            group_versions(self.entries + self.clips, self._group_id_of())
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
    metadata_root: Path | None = None,
) -> LibrarySource:
    """Discover videos + clips and obtain the durations mode-filtering needs.

    Pass *durations* to supply them directly (tests); otherwise a
    *duration_cache* is probed (cached) and persisted.  *scripted_only*
    defaults False (Nau plays everything standalone); pass False to serve
    every video regardless of funscript.  *metadata_root*, when given, makes
    version grouping read Evolver's sidecars instead of guessing from names.
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
        scripted_only=scripted_only, metadata_root=metadata_root,
    )
