"""Clip navigation: the `clip` metadata Evolver records, and the jumps it powers.

A clip carved out of a compilation gets a sidecar ``clip`` object recording its
parent compilation, its running order within it, and the source movie + performer
it was taken from (see Evolver). This module reads that field — mirroring
:func:`nau.library_source.read_version_group` — and turns it into the three
navigations Fun Time exposes:

* ``compilation`` — the clip's siblings, in original order (for a playlist);
* ``full vid``    — the library video the clip's scene was taken from;
* ``money shot``  — the reverse, a full scene's clip.

The source/performer match is deliberately loose (token containment) because a
library file names its scene however the user happened to save it; most sources
are not in the library at all, so a miss (``None``) is the common, expected case.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


def read_clip(video: Path, metadata_root: Path) -> dict | None:
    """The ``clip`` object Evolver recorded for *video*, or None.

    The metadata tree mirrors the video library one-to-one (``…/videos/metadata``
    pairs with ``…/videos/videos``), so the sidecar sits at the same path under
    *metadata_root* as the clip sits under the library root. A missing or
    malformed sidecar, or one with no ``clip`` object, returns None.
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
    clip = payload.get("clip") if isinstance(payload, dict) else None
    return clip if isinstance(clip, dict) else None


_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text.lower()))


def _matches(meta: dict, text: set[str]) -> bool:
    """Whether *text* (a filename's tokens) names this clip's scene.

    Requires every performer token to be present and at least one source-movie
    token to overlap — enough to pair ``Kim Lee - POV Scene 2`` with
    a ``POV Scene 2 - Kim Lee 1080p`` scene while rejecting a
    same-source scene starring someone else.
    """
    perf = _tokens(str(meta.get("performer", "")))
    src = _tokens(str(meta.get("source", "")))
    return bool(perf) and perf <= text and bool(src & text)


@dataclass(frozen=True)
class ClipNav:
    _clips: dict[Path, dict]
    _non_clips: tuple[Path, ...]

    @classmethod
    def build(cls, videos: Iterable[Path], metadata_root: Path | None) -> ClipNav:
        clips: dict[Path, dict] = {}
        non_clips: list[Path] = []
        for video in videos:
            meta = read_clip(video, metadata_root) if metadata_root is not None else None
            if meta is not None:
                clips[video] = meta
            else:
                non_clips.append(video)
        return cls(clips, tuple(non_clips))

    def is_clip(self, video: Path) -> bool:
        return video in self._clips

    def compilation_playlist(self, video: Path) -> list[Path]:
        """The clips of *video*'s compilation in original order, self included.

        Empty when *video* is not a clip.
        """
        meta = self._clips.get(video)
        if meta is None:
            return []
        comp = meta.get("compilation")
        siblings = [
            (m.get("index", 0), v)
            for v, m in self._clips.items()
            if m.get("compilation") == comp
        ]
        return [v for _, v in sorted(siblings, key=lambda iv: (iv[0], str(iv[1])))]

    def full_vid_of(self, video: Path) -> Path | None:
        """The non-clip library video this clip's scene was taken from, or None."""
        meta = self._clips.get(video)
        if meta is None:
            return None
        return next((c for c in self._non_clips if _matches(meta, _tokens(c.stem))), None)

    def clip_of(self, video: Path) -> Path | None:
        """A clip whose source + performer names *video*'s scene, or None."""
        text = _tokens(video.stem)
        return next((v for v, m in self._clips.items() if _matches(m, text)), None)
