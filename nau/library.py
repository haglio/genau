"""Smart library layer for Nau: version grouping, quality dedup, and
length-mode filtering — all pure logic, no pygame or I/O.

Many files in the wild are the same content at different quality or upscale
(``...-1080p_60fps.mp4``, ``...-old_iris2.mp4``, ``..._topaz.mp4``). This
module normalizes titles to fold those variants into a single *version
group*, picks the largest file as the canonical one, and offers a
canonical-only shuffle plus a full-length/shorts filter.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from pathlib import Path


# Tunable heuristic: tokens dropped anywhere in a title because they mark a
# quality/upscaler/codec/resolution/container variant rather than content.
# This is deliberately conservative — the list can over-group (folding two
# genuinely different videos) or under-group (missing an unlisted tag), and is
# meant to be edited as new tags show up in the library.
_QUALITY_TOKENS = frozenset({
    # upscalers / restoration
    "topaz", "iris2", "old_iris2", "upscale", "upscaled", "remux",
    # codecs
    "x264", "x265", "hevc", "av1",
    # frame rates
    "60fps", "30fps", "24fps",
    # resolutions
    "480p", "540", "540p", "720p", "1080p", "1440p", "2160p", "4k",
    # containers / sources
    "mp4", "mkv", "web", "webrip",
})

# "old_iris2" contains an underscore, so it must be matched before the
# separator collapse splits it. Keep the multi-part quality tokens here.
_MULTIPART_QUALITY = tuple(t for t in _QUALITY_TOKENS if "_" in t)

_SEPARATORS = re.compile(r"[-_ .]+")
_HASH_TOKEN = re.compile(r"[a-z0-9]{6,12}")


def _is_hash_token(token: str) -> bool:
    """A short alnum token that mixes letters and digits (e.g. ``ehwgjw62``).

    Requiring both classes keeps pure words (``compilation``) and pure
    numbers (a scene index like ``1``) from being mistaken for hashes.
    """
    if not _HASH_TOKEN.fullmatch(token):
        return False
    return any(c.isalpha() for c in token) and any(c.isdigit() for c in token)


def normalize_title(stem: str) -> str:
    text = stem.lower()
    for token in _MULTIPART_QUALITY:
        text = text.replace(token, " ")
    tokens = [t for t in _SEPARATORS.split(text) if t and t not in _QUALITY_TOKENS]
    while tokens and _is_hash_token(tokens[-1]):
        tokens.pop()
    return " ".join(tokens)


@dataclass(frozen=True)
class LibraryEntry:
    """One playable video plus its optional funscript and file size.

    Size drives canonical selection within a version group (largest wins),
    so it is probed once at discovery and carried through the pipeline.
    """

    video: Path
    funscript: Path | None
    size: int


@dataclass(frozen=True)
class VersionGroup:
    """Entries that normalize to the same title, ordered largest-first.

    The first (largest) entry is the canonical version to shuffle into a
    playlist; the rest are alternates reachable via "cycle version".
    """

    members: tuple[LibraryEntry, ...]

    @property
    def canonical(self) -> LibraryEntry:
        return self.members[0]

    @property
    def alternates(self) -> list[LibraryEntry]:
        return list(self.members[1:])


_VERSION_DUR_TOL_FRAC = 0.02  # 2%
_VERSION_DUR_TOL_MIN_S = 3.0


def _coarse_key(stem: str) -> str:
    """The first two normalized tokens (usually the performer) — the coarse
    bucket within which duration decides same-content versions."""
    tokens = normalize_title(stem).split()
    return " ".join(tokens[:2]) if tokens else normalize_title(stem)


def group_versions(
    entries: list[LibraryEntry],
    durations: dict[Path, float] | None = None,
) -> list[VersionGroup]:
    """Fold entries into same-content version groups.

    Without *durations* (e.g. Fun Time playlists), groups are keyed by the
    full :func:`normalize_title` — only works when the versions share a name.

    With *durations*, grouping is duration-aware, which is what actually
    catches real libraries: files of the same scene at different quality
    (e.g. ``Jane Doe-<hash>.mkv`` vs
    ``Jane Doe-redacted-it-dry-1080p.mp4``) share almost the same runtime but
    almost nothing in their names.  Entries are first coarse-bucketed by
    performer (first two tokens), then clustered within a bucket by runtime
    proximity (within max(3s, 2%)).  Unprobed entries fall back to a title key.

    Within each group members are ordered largest-file first, so the largest
    is canonical.  Group order follows first appearance.
    """
    if durations is None:
        return _group_by_title(entries)

    order: list[str] = []
    coarse: dict[str, list[LibraryEntry]] = {}
    for entry in entries:
        d = durations.get(entry.video, 0.0)
        # Unprobed entries cannot be duration-clustered — key them by full
        # title so they still fold with same-named siblings, not everything.
        key = _coarse_key(entry.video.stem) if d > 0 else "\x00" + normalize_title(entry.video.stem)
        if key not in coarse:
            coarse[key] = []
            order.append(key)
        coarse[key].append(entry)

    groups: list[VersionGroup] = []
    for key in order:
        for cluster in _cluster_by_duration(coarse[key], durations):
            members = sorted(cluster, key=lambda e: (-e.size, str(e.video)))
            groups.append(VersionGroup(members=tuple(members)))
    return groups


def _cluster_by_duration(
    members: list[LibraryEntry], durations: dict[Path, float],
) -> list[list[LibraryEntry]]:
    """Split a coarse bucket into runtime-proximity clusters (sorted input)."""
    with_dur = sorted(members, key=lambda e: durations.get(e.video, 0.0))
    clusters: list[list[LibraryEntry]] = []
    prev: float | None = None
    for entry in with_dur:
        d = durations.get(entry.video, 0.0)
        tol = max(_VERSION_DUR_TOL_MIN_S, _VERSION_DUR_TOL_FRAC * d)
        if prev is not None and d > 0 and prev > 0 and d - prev <= tol:
            clusters[-1].append(entry)
        else:
            clusters.append([entry])
        prev = d
    return clusters


def _group_by_title(entries: list[LibraryEntry]) -> list[VersionGroup]:
    order: list[str] = []
    buckets: dict[str, list[LibraryEntry]] = {}
    for entry in entries:
        key = normalize_title(entry.video.stem)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(entry)
    groups: list[VersionGroup] = []
    for key in order:
        members = sorted(buckets[key], key=lambda e: (-e.size, str(e.video)))
        groups.append(VersionGroup(members=tuple(members)))
    return groups


def canonical_playlist(
    entries: list[LibraryEntry], rng: random.Random,
    durations: dict[Path, float] | None = None,
) -> list[LibraryEntry]:
    """One canonical entry per version group, shuffled with *rng*.

    Deterministic for a given seeded ``random.Random`` so a session (and its
    tests) can reproduce the order.
    """
    canonicals = [group.canonical for group in group_versions(entries, durations)]
    rng.shuffle(canonicals)
    return canonicals


# A "short" is anything this long or shorter; longer videos are full-length.
# Compilations are long, so they are never shorts — the split is duration-only.
SHORT_MAX_S = 60.0

FULL = "full"
SHORTS = "shorts"


def select_library(
    entries: list[LibraryEntry],
    *,
    mode: str,
    durations: dict[Path, float],
    clips: list[LibraryEntry],
    scripted_only: bool = False,
) -> list[LibraryEntry]:
    """Filter *entries* by length *mode*, then version-dedup the survivors.

    Full-length mode keeps entries whose probed duration exceeds
    :data:`SHORT_MAX_S`; shorts mode keeps entries at or under it *and* always
    includes *clips* (saved clip videos, treated as shorts regardless of
    length). Entries with no probed duration cannot be classified and are
    dropped. When *clips* is empty, shorts mode is purely duration-driven.

    *scripted_only* (the standalone default — Nau standalone is the funscript
    loop tool) drops main entries with no funscript so the R gesture always
    has something to loop; *clips* are always included regardless, since
    shorts mode exists to surface them.

    Returns one canonical entry per surviving version group.
    """
    if scripted_only:
        entries = [e for e in entries if e.funscript is not None]
    if mode == SHORTS:
        kept = [e for e in entries if durations.get(e.video, float("inf")) <= SHORT_MAX_S]
        kept += clips
    else:
        kept = [e for e in entries if durations.get(e.video, 0.0) > SHORT_MAX_S]
    return [group.canonical for group in group_versions(kept, durations)]


def entries_to_pairs(entries: list[LibraryEntry]) -> list[tuple[Path, Path | None]]:
    """Drop file sizes, leaving the (video, funscript) pairs the session wants."""
    return [(e.video, e.funscript) for e in entries]


def version_index_from_groups(
    groups: list[VersionGroup],
) -> dict[Path, list[tuple[Path, Path | None]]]:
    """Map every video to its group's (video, funscript) pairs, largest-first.

    This is what :meth:`PlayerSession.cycle_version` consults to walk between
    versions of the same content — each member points at the same ordered
    pair list, so cycling is stable regardless of which one is playing.
    """
    index: dict[Path, list[tuple[Path, Path | None]]] = {}
    for group in groups:
        members = [group.canonical, *group.alternates]
        pairs = entries_to_pairs(members)
        for entry in members:
            index[entry.video] = pairs
    return index


def library_playlist(
    entries: list[LibraryEntry],
    *,
    mode: str,
    durations: dict[Path, float],
    clips: list[LibraryEntry],
    rng: random.Random,
    scripted_only: bool = False,
) -> list[tuple[Path, Path | None]]:
    """Full standalone build: filter by *mode*, version-dedup, shuffle, pair.

    Deterministic for a seeded *rng*. This is the single composition both
    startup and the length-mode toggle use, so their playlists stay
    consistent.
    """
    selected = select_library(
        entries, mode=mode, durations=durations, clips=clips, scripted_only=scripted_only,
    )
    return entries_to_pairs(canonical_playlist(selected, rng, durations))
