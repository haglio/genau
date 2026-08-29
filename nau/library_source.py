"""Standalone library source: discovered entries + durations + clips.

Bundles everything the length-mode toggle needs so startup and the runtime
switch build playlists from the same data. Fun Time drives its own explicit
playlist and does not use this.
"""
from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .discovery import discover_entries
from .duration_cache import DurationCache
from .library import (
    MIXED,
    SHORTS,
    FULL,
    LibraryEntry,
    group_versions,
    library_playlist,
    version_index_from_groups,
)
from .sidecar import read_version_group, read_video_type

# The app starts unfiltered — which is what Fun Time's own playlist has always
# been, so a player that opened claiming "full length" was claiming a filter it
# was not running.  The toggle walks all three in this order and wraps.
LENGTH_MODES = (MIXED, SHORTS, FULL)
DEFAULT_MODE = MIXED


def next_length_mode(mode: str) -> str:
    """The mode after *mode* in the cycle, wrapping; the default from anywhere
    outside it, so the toggle always lands on a real mode."""
    if mode not in LENGTH_MODES:
        return DEFAULT_MODE
    return LENGTH_MODES[(LENGTH_MODES.index(mode) + 1) % len(LENGTH_MODES)]


def length_mode_rebuilds(requested: str, current: str, *, in_compilation: bool) -> bool:
    """Whether asking for *requested* while running *current* has work to do.

    Naming the mode already running asks for nothing, and the rebuild it would
    trigger is not nothing: the playlist is reshuffled and landed on at entry 0,
    so saying "mixed" twice puts two different videos on screen.  Fun Time's reset
    says it on every press, which made a control meaning "put it back" the
    quickest way to keep changing what was playing.

    Inside a compilation the same words do have work, and are the point:
    PLAY_COMPILATION swaps the playlist for one volume's clips without touching
    the mode, so naming a length is the way back out — there an unchanged mode is
    exactly the case that must rebuild.
    """
    return requested != current or in_compilation

# The two waits a caller can put a loading screen behind.  Walking the library
# tree has no count to report until it finishes, so it reports (0, 0); probing
# durations counts entries, and is the phase that can run to tens of seconds on
# a cold cache — one ffprobe per unprobed video.  Naming the phases (rather than
# passing display text) keeps the wording where the screen is.
PHASE_DISCOVER = "discover"
PHASE_DURATIONS = "durations"


@dataclass(frozen=True)
class LibrarySource:
    entries: list[LibraryEntry]
    clips: list[LibraryEntry]
    durations: dict[Path, float]
    rng: random.Random
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
            kind_of=self._kind_of(),
        )

    def _group_id_of(self) -> Callable[[Path], str | None] | None:
        if self.metadata_root is None:
            return None
        metadata_root = self.metadata_root
        return lambda video: read_version_group(video, metadata_root)

    def _kind_of(self) -> Callable[[Path], str] | None:
        """Reader for the kind Evolver recorded — the length modes' authority."""
        if self.metadata_root is None:
            return None
        metadata_root = self.metadata_root
        return lambda video: read_video_type(video, metadata_root)

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
    metadata_root: Path | None = None,
    on_progress: Callable[[str, int, int], None] | None = None,
) -> LibrarySource:
    """Discover videos + clips and obtain the durations mode-filtering needs.

    Pass *durations* to supply them directly (tests); otherwise a
    *duration_cache* is probed (cached) and persisted — for the entries that
    need one, which is those whose kind Evolver has not recorded yet.  Every
    video is served: Nau standalone is a general player, and narrowing to
    scripted videos is Fun Time's F-mode.  *metadata_root*, when given, makes
    version grouping read Evolver's sidecars instead of guessing from names.

    *on_progress* is called ``(phase, done, total)`` as the work the user waits
    through proceeds — before each phase and before each duration probe, so the
    count reported is the work already behind it.  It may raise to abort the
    build; nothing here catches that, which is how the loading screen turns a
    closed window into an immediate exit rather than one deferred to the end.
    """
    report = on_progress if on_progress is not None else lambda *_: None
    report(PHASE_DISCOVER, 0, 0)
    entries = discover_entries(videos_dir, scripts_dir)
    clips = discover_clips(clips_dir)
    if durations is None:
        if duration_cache is None:
            raise ValueError("either durations or duration_cache must be given")
        durations = {}
        for done, entry in enumerate(entries):
            report(PHASE_DURATIONS, done, len(entries))
            if metadata_root is not None and read_video_type(entry.video, metadata_root):
                # Its kind is on file, which is the only thing a duration was
                # ever wanted for — and this probe is the whole of startup's
                # wait, so a library Evolver has been over opens without one.
                continue
            durations[entry.video] = duration_cache.duration_for(entry.video)
        duration_cache.save()
    return LibrarySource(
        entries=entries, clips=clips, durations=durations, rng=rng,
        metadata_root=metadata_root,
    )
