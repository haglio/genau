"""Smart library layer for Nau: version grouping, quality dedup, and
length-mode filtering — all pure logic, no pygame or I/O.

Many files in the wild are the same content at different quality or upscale
(``...-1080p_60fps.mp4``, ``...-old_iris2.mp4``, ``..._topaz.mp4``). This
module folds those variants into a single *version group* keyed on the name —
an upscale is almost always the original's name plus an appended tag — picks
the largest file as the canonical one, and offers a canonical-only shuffle, a
Fun-Time playlist collapse, and a full-length/shorts filter.
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
    """Entries that are versions of one video, ordered largest-first.

    Members share a title prefix — an upscale is the original's name plus a
    tag. The first (largest) entry is the canonical version to shuffle into a
    playlist; the rest are alternates reachable via "cycle version".
    """

    members: tuple[LibraryEntry, ...]

    @property
    def canonical(self) -> LibraryEntry:
        return self.members[0]

    @property
    def alternates(self) -> list[LibraryEntry]:
        return list(self.members[1:])


def _title_tokens(stem: str) -> tuple[str, ...]:
    return tuple(normalize_title(stem).split())


def _is_prefix(shorter: tuple[str, ...], longer: tuple[str, ...]) -> bool:
    """Whether *shorter*'s tokens begin *longer*'s (equal counts as a prefix)."""
    return len(shorter) <= len(longer) and longer[: len(shorter)] == shorter


def _matching_group(
    groups: list[list[LibraryEntry]],
    group_tokens: list[tuple[str, ...]],
    toks: tuple[str, ...],
) -> list[LibraryEntry] | None:
    """The existing group whose title begins *toks*, or None.

    An empty *toks* (a name of only quality/hash tokens) matches nothing, so
    such a file stands alone rather than swallowing every other singleton.
    """
    if not toks:
        return None
    for members, gtoks in zip(groups, group_tokens):
        if gtoks and _is_prefix(gtoks, toks):
            return members
    return None


def group_versions(entries: list[LibraryEntry]) -> list[VersionGroup]:
    """Fold entries into same-content version groups, by name alone.

    Two files are the same video when one's normalized title is a token-wise
    *prefix* of the other's — the overwhelmingly common case of upscaling a
    video and appending a tag to its name (``scene`` vs ``scene_topaz_v2``).
    Duration is deliberately not consulted: real re-encodes and re-trims drift
    a handful of seconds, and a shared name prefix is the reliable signal,
    where a shared runtime would fold genuinely different scenes of like length.

    Entries are matched shortest-title-first, so an original anchors the group
    its longer-named upscales join. Within a group members are ordered
    largest-file first (canonical first); group order follows first appearance.
    """
    order = {entry: i for i, entry in enumerate(entries)}
    tokens = {entry: _title_tokens(entry.video.stem) for entry in entries}
    groups: list[list[LibraryEntry]] = []
    group_tokens: list[tuple[str, ...]] = []
    for entry in sorted(entries, key=lambda e: (len(tokens[e]), order[e])):
        toks = tokens[entry]
        anchor = _matching_group(groups, group_tokens, toks)
        if anchor is None:
            groups.append([entry])
            group_tokens.append(toks)
        else:
            anchor.append(entry)
    groups.sort(key=lambda members: min(order[m] for m in members))
    return [
        VersionGroup(members=tuple(sorted(members, key=lambda e: (-e.size, str(e.video)))))
        for members in groups
    ]


def collapse_playlist_versions(
    pairs: list[tuple[Path, Path | None]],
    version_index: dict[Path, list[tuple[Path, Path | None]]],
) -> list[tuple[Path, Path | None]]:
    """Dedupe a playlist to one entry per version group, order preserved.

    *version_index* (from :func:`version_index_from_groups`) maps each known
    video to its group's pairs, largest-first. Each group is emitted once, at
    its first-seen position, keeping the largest member actually present in
    *pairs* (with that member's funscript from *pairs*). Videos absent from the
    index pass through unchanged. This turns Fun Time's raw per-file playlist
    into the one-slot-per-video rotation the primary player shows, matching the
    set :meth:`PlayerSession.cycle_version` walks.
    """
    funscript_by_video = {video: funscript for video, funscript in pairs}
    present = set(funscript_by_video)
    collapsed: list[tuple[Path, Path | None]] = []
    seen: set[Path] = set()
    for video, _funscript in pairs:
        members = version_index.get(video)
        if members:
            group_id = members[0][0]
            keep = next((v for v, _ in members if v in present), video)
        else:
            group_id = video
            keep = video
        if group_id in seen:
            continue
        seen.add(group_id)
        collapsed.append((keep, funscript_by_video.get(keep)))
    return collapsed


def canonical_playlist(
    entries: list[LibraryEntry], rng: random.Random,
) -> list[LibraryEntry]:
    """One canonical entry per version group, shuffled with *rng*.

    Deterministic for a given seeded ``random.Random`` so a session (and its
    tests) can reproduce the order.
    """
    canonicals = [group.canonical for group in group_versions(entries)]
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
    return [group.canonical for group in group_versions(kept)]


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
    return entries_to_pairs(canonical_playlist(selected, rng))
