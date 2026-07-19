"""Locating a clip inside the scene it was cut from, by its own frames.

A compilation clip is a literal excerpt of a library scene, so the scene's
timeline contains the clip's pictures verbatim. Sampling frames from both,
hashing them and looking for the offset that lines them up therefore answers the
question the filenames cannot — the user's library names scenes
``Performer_540-hash``, with no movie title to match against, so
:mod:`nau.clip_nav` can only pair a performer's single scene with their single
clip and has to decline the rest.

Run as a batch (``python -m nau.clip_match``); it writes what it finds into the
clip sidecars, where clip_nav reads it back at no cost.
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import numpy as np
from app_support.subprocess_utils import hidden_subprocess_kwargs

from .cli import DEFAULT_CONFIG, load_config
from .clip_nav import could_be_cut_from
from .discovery import discover_entries
from .library import LibraryEntry, VersionGroup, group_versions
from .sidecar import read_clip, read_sidecar, read_version_group, sidecar_for

logger = logging.getLogger(__name__)

# The hash is 8 rows of 9 cells compared left-to-right, so a sampled frame is a
# whole multiple of that — pooling then divides exactly and no pixel is dropped.
_ROWS, _COLS = 8, 9
SAMPLE_HEIGHT, SAMPLE_WIDTH = _ROWS * 4, _COLS * 4

# Both sides are sampled on one grid, so the worst a clip frame can be out by is
# half a step — 60ms, less than two frames of the videos themselves.
SAMPLE_FPS = 8.0

# A frame survives re-encoding, rescaling and upscaling with its hash almost but
# not quite intact, so "the same picture" is a small Hamming distance, not zero.
TOLERANCE = 8

# How far either side of an offset its own frames can land, in samples. The two
# videos are sampled off different source frame rates, so one excerpt's frames
# answer to a small spread of offsets rather than to exactly one.
JITTER = 1

# How much of a clip has to turn up at one offset before that offset is the
# answer. A real excerpt places nearly all of itself; scattered lookalikes place
# a frame or two each, so anything in between is a wide, safe gap.
MIN_SCORE = 0.25

_POPCOUNT = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint8)


def sample_frames(video: Path, fps: float) -> np.ndarray:
    """*video* decoded to gray thumbnails, *fps* of them a second.

    Empty when ffmpeg cannot read the file, which leaves that video matching
    nothing rather than stopping the batch. Files with damaged frames do decode,
    complaining on stderr the whole way — held back unless the run really fails,
    since a batch over hundreds of videos is unreadable otherwise.
    """
    command = [
        "ffmpeg", "-v", "error", "-i", str(video), "-an",
        # Averaging the whole source block, rather than sampling a few pixels of
        # it, is what makes a 4K upscale thumbnail like its 540p original.
        "-vf", f"fps={fps},scale={SAMPLE_WIDTH}:{SAMPLE_HEIGHT}:flags=area",
        "-pix_fmt", "gray", "-f", "rawvideo", "-",
    ]
    try:
        raw = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
            **hidden_subprocess_kwargs(),
        ).stdout
    except subprocess.CalledProcessError as exc:
        logger.warning("could not sample %s: %s", video.name, exc.stderr.decode(errors="replace"))
        raw = b""
    except OSError as exc:
        logger.warning("could not sample %s: %s", video.name, exc)
        raw = b""
    pixels = SAMPLE_HEIGHT * SAMPLE_WIDTH
    count = len(raw) // pixels
    return np.frombuffer(raw[: count * pixels], dtype=np.uint8).reshape(
        count, SAMPLE_HEIGHT, SAMPLE_WIDTH
    )


def frame_hashes(frames: np.ndarray) -> np.ndarray:
    """A 64-bit difference hash per frame of *frames* (n x height x width, gray).

    Each frame is mean-pooled to 8x9 cells and every cell compared with its
    right-hand neighbour. Reading *relative* brightness is what lets a clip's
    frame match the same frame in a scene encoded at another resolution,
    bitrate or gamma.
    """
    pooled = _pool(frames)
    bits = pooled[:, :, 1:] > pooled[:, :, :-1]
    return np.packbits(bits.reshape(len(frames), 64), axis=1).view(">u8").ravel()


def _pool(frames: np.ndarray) -> np.ndarray:
    """*frames* averaged down to the hash's 8x9 grid of cells."""
    count, height, width = frames.shape
    return frames.reshape(
        count, _ROWS, height // _ROWS, _COLS, width // _COLS,
    ).mean(axis=(2, 4))


@dataclass(frozen=True)
class Alignment:
    """Where a clip sits in a scene, and how much of it was found there."""

    offset: float
    score: float


def align(clip: np.ndarray, scene: np.ndarray, *, fps: float) -> Alignment | None:
    """Where *clip*'s frames sit in *scene*'s, or None if they do not.

    Both are frame-hash runs sampled at *fps*. Every near-equal pair of frames
    votes for the offset that would explain it; the offset the most clip frames
    agree on wins, and has to carry :data:`MIN_SCORE` of the clip to count.

    Neighbouring offsets count together. Sampling 8 frames a second off a 24fps
    scene lands on exact source frames and off a 30fps clip does not, so one
    excerpt's frames answer to offsets a bucket either side of the true one; the
    single best bucket holds only a fraction of a real match.
    """
    close = _distances(clip, scene) <= TOLERANCE
    if not close.any():
        return None
    clip_frame, scene_frame = np.nonzero(close)
    shift = scene_frame - clip_frame
    best = _peak(shift)
    # Distinct frames, since one clip frame can answer to every offset in the
    # window; without that a still moment could score above a whole excerpt.
    backers = np.unique(clip_frame[np.abs(shift - best) <= JITTER])
    score = len(backers) / len(clip)
    return Alignment(offset=best / fps, score=score) if score >= MIN_SCORE else None


def _peak(shift: np.ndarray) -> int:
    """The offset whose window of neighbours carries the most votes."""
    low = int(shift.min())
    counts = np.bincount(shift - low)
    window = np.convolve(counts, np.ones(2 * JITTER + 1, dtype=int), mode="same")
    return int(window.argmax()) + low


def _distances(clip: np.ndarray, scene: np.ndarray) -> np.ndarray:
    """Hamming distance between every clip hash and every scene hash."""
    xor = (clip[:, None] ^ scene[None, :]).view(np.uint8).reshape(len(clip), len(scene), 8)
    return _POPCOUNT[xor].sum(axis=2, dtype=np.uint8)


@dataclass(frozen=True)
class Match:
    """The one candidate clip a scene turned out to contain."""

    clip: Path
    offset: float
    score: float


def locate(scene: np.ndarray, candidates: dict[Path, np.ndarray], *, fps: float) -> Match | None:
    """Which of *candidates* was cut from *scene*, and where, or None.

    Candidates come from the names — every clip whose performer the scene's
    filename mentions — so most of them were cut from the same performer's other
    scenes and belong nowhere in this one. The best-aligning candidate wins; a
    scene that never made it into a compilation has no aligning candidate at all.
    """
    found = {
        clip: alignment
        for clip, hashes in candidates.items()
        if (alignment := align(hashes, scene, fps=fps)) is not None
    }
    if not found:
        return None
    clip = max(found, key=lambda candidate: found[candidate].score)
    return Match(clip=clip, offset=found[clip].offset, score=found[clip].score)


def record(clip: Path, scene: Path, *, offset: float, metadata_root: Path) -> None:
    """Write the scene *clip* came from, and where in it, into *clip*'s sidecar.

    ``scene_offset`` is seconds into *scene* — nothing reads it yet, but it is
    what a funscript has to be shifted by to fit the clip, and it is only
    knowable while the alignment that found it is still in hand.
    """
    path = sidecar_for(clip, metadata_root)
    if path is None:
        return
    payload = read_sidecar(clip, metadata_root)
    payload.setdefault("clip", {}).update(full_video=str(scene), scene_offset=offset)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def match_library(
    entries: list[LibraryEntry],
    metadata_root: Path,
    *,
    fps: float = SAMPLE_FPS,
    sampler: Callable[[Path, float], np.ndarray] = sample_frames,
    on_scene: Callable[[Path, Match | None], None] | None = None,
) -> dict[Path, Match]:
    """Find the clip cut from each scene in *entries*, recording what it finds.

    Works from the scenes, which are the complete set: every compilation clip
    came from one of them, while most scenes were never in a compilation and
    correctly end up with no match. Recording waits for the whole sweep, since
    two scenes can turn out to hold one clip; the answer then goes to the
    sidecar of every version of the winning clip, so it holds whichever one is
    played.

    *on_scene* is called with each scene and what aligned to it as the sweep
    goes, since it reads every candidate video end to end and takes minutes.
    """
    metas = {entry.video: read_clip(entry.video, metadata_root) for entry in entries}
    # Evolver's recorded version family, not the name prefix Nau falls back to:
    # two scenes of one performer can share a prefix without being one video, and
    # folding them would decode the one and leave the other unmatchable.
    versions = partial(read_version_group, metadata_root=metadata_root)
    clips = group_versions([e for e in entries if metas[e.video] is not None], versions)
    scenes = group_versions([e for e in entries if metas[e.video] is None], versions)
    families = {_cheapest(family): family for family in clips}
    hashes: dict[Path, np.ndarray] = {}

    def hashed(video: Path) -> np.ndarray:
        # A clip is a candidate for every scene of its performer, so cache it.
        if video not in hashes:
            hashes[video] = frame_hashes(sampler(video, fps))
        return hashes[video]

    matched: dict[Path, Match] = {}
    for scene_family in scenes:
        scene = _cheapest(scene_family)
        candidates = {
            video: family for video, family in families.items()
            if could_be_cut_from(metas[family.canonical.video], scene_family.canonical.video)
        }
        found = (
            locate(hashed(scene), {video: hashed(video) for video in candidates}, fps=fps)
            if candidates else None
        )
        if found is not None:
            matched[scene] = found
        if on_scene is not None:
            on_scene(scene, found)

    matched = _best_scene_per_clip(matched)
    for scene, match in matched.items():
        for member in families[match.clip].members:
            record(member.video, scene, offset=match.offset, metadata_root=metadata_root)
    return matched


def _best_scene_per_clip(matched: dict[Path, Match]) -> dict[Path, Match]:
    """*matched* with each clip left to the one scene that holds it best.

    The library keeps both a 540p release and a 4k re-release of the odd scene,
    trimmed differently, and a clip really does sit inside each — but only one of
    them can be its ``full_video``, so the closer alignment takes it rather than
    whichever scene the sweep happened to reach last.
    """
    winner: dict[Path, Path] = {}
    for scene, match in matched.items():
        held = winner.get(match.clip)
        if held is None or matched[held].score < match.score:
            winner[match.clip] = scene
    return {scene: matched[scene] for scene in matched if scene in set(winner.values())}


def _cheapest(family: VersionGroup) -> Path:
    """The version of a video that costs least to decode.

    Members are ordered largest-first, and an upscale is many times the size of
    its original — minutes rather than seconds to read — for pictures that are
    the same either way.
    """
    return family.members[-1].video


def main(argv: list[str] | None = None) -> int:
    """Run the match over the configured library, reporting scene by scene."""
    parser = argparse.ArgumentParser(
        description="Record in each clip's sidecar which library scene it was cut from.",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    nau = load_config(args.config).get("nau", {})
    missing = [key for key in ("videos_dir", "scripts_dir", "metadata_dir") if not nau.get(key)]
    if missing:
        parser.error(f"{args.config} sets no {', '.join(missing)}")

    entries = discover_entries(Path(nau["videos_dir"]), Path(nau["scripts_dir"]))
    matched = match_library(entries, Path(nau["metadata_dir"]), on_scene=_report)
    print(f"\n{len(matched)} scenes matched to a clip.")
    return 0


def _report(scene: Path, match: Match | None) -> None:
    if match is None:
        print(f"  ---- {scene.name}", flush=True)
        return
    print(f"  {match.score:4.0%} {scene.name} @{match.offset:.1f}s <- {match.clip.name}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
