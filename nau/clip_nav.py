"""Clip navigation: the `clip` metadata Evolver records, and the jumps it powers.

A clip carved out of a compilation gets a sidecar ``clip`` object recording its
parent compilation, its running order within it, and the source movie + performer
it was taken from (see Evolver). This module reads that field — mirroring
:func:`nau.library_source.read_version_group` — and turns it into the three
navigations Fun Time exposes:

* ``compilation`` — the clip's siblings, in original order (for a playlist);
* ``full vid``    — the library video the clip's scene was taken from;
* ``money shot``  — the reverse, a full scene's clip.

``full vid``/``money shot`` answer from a ``full_video`` the sidecar records when
one is there: :mod:`nau.clip_match` found the clip's own frames inside that scene,
so it beats any reading of the names. Without one they fall back to matching the
source/performer against the filename — deliberately loose (token containment)
because a library file names its scene however the user happened to save it, and
often enough carries no movie title at all. Most sources are not in the library,
so a miss (``None``) is the common, expected case either way.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .library import normalize_title


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


def _size(video: Path) -> int:
    try:
        return video.stat().st_size
    except OSError:
        return 0


# Words too common to identify a movie ("Best of Times", "A for Ambrose").
_STOPWORDS = frozenset({"the", "and", "for", "of", "a", "an", "in", "to", "my", "it", "on"})


def _distinctive(source: str, performer: str) -> set[str]:
    """Source-title words that actually identify the movie.

    The performer's own name is stripped out: a title like *Jane Doe To the Brink* would otherwise match every Jane Doe file in the library on her name
    alone. Stopwords and one/two-letter fragments go too.
    """
    perf = _tokens(performer)
    return {t for t in _tokens(source) - perf if len(t) > 2 and t not in _STOPWORDS}


def _matches(meta: dict, text: set[str]) -> bool:
    """Whether *text* (a filename's tokens) names this clip's scene.

    Requires every performer token to be present *and* at least one distinctive
    source-title word — enough to pair ``Ann Bly - POV Scene 2``
    with a ``redacted---POV-redacted-2-(2009)`` scene, while rejecting
    both a same-source scene starring someone else and an unrelated file that
    merely shares the performer.
    """
    perf = _tokens(str(meta.get("performer", "")))
    if not perf or not perf <= text:
        return False
    distinctive = _distinctive(str(meta.get("source", "")), str(meta.get("performer", "")))
    return bool(distinctive) and bool(distinctive & text)


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

    def compilation_of(self, video: Path) -> str:
        """The title of the compilation *video* was carved from, or "" for a
        non-clip.  Nau's HUD names it, so the player can say what is holding the
        playlist rather than leaving it to be inferred from the clips."""
        meta = self._clips.get(video)
        return str(meta.get("compilation", "") or "") if meta is not None else ""

    def compilation_playlist(self, video: Path) -> list[Path]:
        """The clips of *video*'s compilation in original order, self included.

        Empty when *video* is not a clip.
        """
        meta = self._clips.get(video)
        if meta is None:
            return []
        comp = meta.get("compilation")
        # One slot per scene: an upscaled variant carries the same clip object as
        # its original, so keep only the largest file for each running index —
        # the same "canonical is biggest" rule the version grouping uses.
        best: dict[int, Path] = {}
        for video, m in self._clips.items():
            if m.get("compilation") != comp:
                continue
            index = m.get("index", 0)
            current = best.get(index)
            if current is None or _size(video) > _size(current):
                best[index] = video
        return [best[i] for i in sorted(best)]

    def full_vid_of(self, video: Path) -> Path | None:
        """The non-clip library video this clip's scene was taken from, or None.

        A recorded ``full_video`` answers outright; otherwise the names decide.
        """
        meta = self._clips.get(video)
        if meta is None:
            return None
        key = _recorded_key(meta)
        recorded = _largest([s for s in self._non_clips if _scene_key(s) == key])
        if recorded is not None:
            return recorded
        return _resolve(meta, [c for c in self._non_clips if c != video])

    def clip_of(self, video: Path) -> Path | None:
        """The clip carved from *video*'s scene, or None.

        The reverse of :meth:`full_vid_of`, and recorded matches win here too:
        the clip that recorded *this* scene is the answer, whichever version of
        either is on screen.

        Never the file you are already on: a clip matches its own name, which
        would just replay it. Being on a clip already means there is nothing to
        jump to — its siblings are a different scene, not this one's money shot.
        """
        if video in self._clips:
            return None
        key = _scene_key(video)
        recorded = _largest([v for v, m in self._clips.items() if _recorded_key(m) == key])
        if recorded is not None:
            return recorded
        text = _tokens(video.stem)
        named = _largest([v for v, m in self._clips.items() if v != video and _matches(m, text)])
        if named is not None:
            return named
        # Falling back to the performer alone has to hold in *both* directions:
        # one clip for them, and this scene their only one. One clip against
        # several scenes still leaves which scene it came from unknowable, so a
        # pairing there would be a guess dressed as an answer.
        candidates = [
            v for v, m in self._clips.items()
            if v != video and _performer_of(m) and _performer_of(m) <= text
        ]
        only_clip = _only_candidate(candidates)
        if only_clip is None:
            return None
        performer = _performer_of(self._clips[only_clip])
        scenes = [s for s in self._non_clips if performer <= _tokens(s.stem)]
        return only_clip if _only_candidate(scenes) is not None else None


def _performer_of(meta: dict) -> set[str]:
    return _tokens(str(meta.get("performer", "")))


def _largest(candidates: list[Path]) -> Path | None:
    """The biggest of *candidates*, or None when there are none.

    Biggest is canonical throughout the library layer: several files matching
    one scene are versions of it, and the largest is the best of them.
    """
    return max(candidates, key=_size) if candidates else None


def _scene_key(scene: Path) -> str:
    """A scene's identity, indifferent to which version of it is on disk.

    ``X.mp4`` and ``X_apo8_iris2.mp4`` are the same scene, so a match recorded
    against one resolves from the other — which is what makes the recorded
    answer survive both "cycle version" and Evolver reprocessing the file.
    """
    return normalize_title(_strip_processing(scene.stem))


def _recorded_key(meta: dict) -> str | None:
    """The :func:`_scene_key` of the scene :mod:`nau.clip_match` recorded, if any."""
    recorded = meta.get("full_video")
    return _scene_key(Path(str(recorded))) if recorded else None


def _only_candidate(candidates: list[Path]) -> Path | None:
    """The one scene among *candidates*, or None when they are several.

    Re-encodes of one video are not "several": ``X.mp4`` and ``X_iris2.mp4`` are
    the same scene, so they collapse under :func:`_scene_key` first. The largest
    survivor wins, the canonical-is-biggest rule used elsewhere.
    """
    if not candidates:
        return None
    by_title: dict[str, list[Path]] = {}
    for candidate in candidates:
        by_title.setdefault(_scene_key(candidate), []).append(candidate)
    if len(by_title) != 1:
        return None
    return _largest(next(iter(by_title.values())))


def _resolve(meta: dict, candidates: list[Path]) -> Path | None:
    """The library file *meta*'s scene was taken from, or None.

    Two tiers, because filenames in the wild carry wildly different detail. A
    name that repeats the movie ("...POV-redacted-2-(2009)...") is matched
    outright. A name that carries only the performer ("redacted_540-hash")
    can still be resolved — but only when that performer has exactly one scene
    here, since with several there is no way to tell which one it was.
    """
    named = _largest([c for c in candidates if _matches(meta, _tokens(c.stem))])
    if named is not None:
        return named
    performer = _performer_of(meta)
    if not performer:
        return None
    return _only_candidate([c for c in candidates if performer <= _tokens(c.stem)])


# Evolver names an enhanced file by appending the models that made it, so
# "scene_apo8_iris2" is "scene". normalize_title knows some of these as quality
# tokens but not all — "apo8" slipped through, which made a scene and its own
# upscale look like two different scenes and killed the match.
_PROCESSING_SUFFIXES = (
    "_topaz_cfr", "_topaz", "_gcg5", "_prob4", "_ghq5",
    "_iris3", "_iris2", "_apf2", "_apo8", "_enh",
)


def _strip_processing(stem: str) -> str:
    """*stem* with every trailing processing suffix removed."""
    changed = True
    while changed:
        changed = False
        for suffix in _PROCESSING_SUFFIXES:
            if stem.endswith(suffix):
                stem, changed = stem[: -len(suffix)], True
    return stem
