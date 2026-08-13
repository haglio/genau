"""Locating a clip inside the scene it was cut from, by its own frames.

A compilation clip is a literal excerpt of a library scene, so the scene's
timeline contains the clip's pictures verbatim. Sampling frames from both,
hashing them and looking for the offset that lines them up therefore answers the
question the filenames cannot — the user's library names scenes
``Performer_540-hash``, with no movie title to match against, so
:mod:`nau.clip_nav` can only pair a performer's single scene with their single
clip and has to decline the rest.

Black bars are cut off both sides before any of that. A hash reads a frame as a
grid of cells, so it is a statement about where things sit in the picture — and
a compilation that pillarboxed a 4:3 scene into a 16:9 frame has moved
everything inward by an eighth without changing a pixel of it. Bars are the
frame around a picture rather than part of it, so they come off first and the
grid lands on the same content either side.

Run as a batch (``python -m nau.clip_match``); it writes what it finds into the
clip sidecars, where clip_nav reads it back at no cost.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import numpy as np
from app_support.subprocess_utils import hidden_subprocess_kwargs

from .cli import DEFAULT_CONFIG, load_config
from .clip_nav import could_be_cut_from
from .discovery import discover_entries
from .library import LibraryEntry, VersionGroup, group_versions, stable_title
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

# Where in a video to look for its bars, as fractions of its runtime, and for how
# long each time. Bars are a constant of the encode, so a few seconds anywhere
# show them — but a fade or a dark shot reads as bars that are not there, and
# cropping a scene its clip does not crop is how a real pair *stops* matching. So
# several windows are unioned: the widest picture any of them saw is the one
# really there, which makes a mistake here cost a crop rather than a match.
PROBE_POINTS = (0.2, 0.5, 0.8)
PROBE_SECONDS = 4.0

# ffmpeg's own reading of "black" (anything this dark), and the multiple it
# rounds the rectangle it finds to.
_CROP_LIMIT, _CROP_ROUND = 24, 2

# A picture smaller than this much of the frame is a dark scene being read as
# bars rather than bars: no real letterbox takes half the height.
MIN_PICTURE_FRACTION = 0.5

_CROP_REPORT = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")


def picture_box(
    reports: Iterable[str], width: int, height: int,
) -> tuple[int, int, int, int] | None:
    """The ``crop=w:h:x:y`` of the picture inside *width* x *height*, or None.

    None means "use the frame as it is" — either nothing was measured, or what
    was measured is the whole frame, or it is so small that a dark shot is the
    likelier explanation. Every *reports* rectangle is taken in, since a window
    can only ever find bars that are not there (see :data:`PROBE_POINTS`), and
    the union of them all is the least-cropped reading.
    """
    corners = [
        (int(x), int(y), int(x) + int(w), int(y) + int(h))
        for report in reports
        for w, h, x, y in _CROP_REPORT.findall(report)
    ]
    if not corners:
        return None
    left = min(corner[0] for corner in corners)
    top = min(corner[1] for corner in corners)
    right = max(corner[2] for corner in corners)
    bottom = max(corner[3] for corner in corners)

    # Chroma is subsampled, so an odd rectangle is one ffmpeg's crop refuses.
    # Rounding outward keeps this the widest reading rather than the tightest.
    left, top = max(0, left - left % 2), max(0, top - top % 2)
    box_width = min(width - left, right - left + right % 2)
    box_height = min(height - top, bottom - top + bottom % 2)
    box_width, box_height = box_width - box_width % 2, box_height - box_height % 2

    if box_width >= width and box_height >= height:
        return None
    if box_width < width * MIN_PICTURE_FRACTION or box_height < height * MIN_PICTURE_FRACTION:
        return None
    return box_width, box_height, left, top


def _probe(video: Path) -> tuple[int, int, float] | None:
    """*video*'s coded width, height and duration, or None if ffprobe cannot say."""
    command = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height:format=duration", "-of", "json", str(video),
    ]
    try:
        probed = json.loads(subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
            **hidden_subprocess_kwargs(),
        ).stdout)
        stream = probed["streams"][0]
        return int(stream["width"]), int(stream["height"]), float(probed["format"]["duration"])
    except (subprocess.CalledProcessError, OSError, ValueError, LookupError):
        return None


def _cropdetect(video: Path, at: float) -> str:
    """What ffmpeg's cropdetect says about the seconds of *video* from *at*."""
    command = [
        "ffmpeg", "-nostats", "-ss", f"{at:.3f}", "-t", str(PROBE_SECONDS),
        "-i", str(video), "-an",
        # reset=0: the rectangle accumulates over the whole window rather than
        # being re-measured per frame, so one dark moment cannot narrow it.
        "-vf", f"cropdetect={_CROP_LIMIT}:{_CROP_ROUND}:0", "-f", "null", "-",
    ]
    try:
        return subprocess.run(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            **hidden_subprocess_kwargs(),
        ).stderr.decode(errors="replace")
    except OSError as exc:
        logger.warning("could not measure %s: %s", video.name, exc)
        return ""


def content_crop(video: Path) -> tuple[int, int, int, int] | None:
    """The ``crop=w:h:x:y`` that leaves *video*'s picture without its bars.

    None when it has none worth cutting, which is most videos.
    """
    probed = _probe(video)
    if probed is None:
        return None
    width, height, duration = probed
    reports = [_cropdetect(video, duration * point) for point in PROBE_POINTS]
    return picture_box(reports, width, height)


def sample_frames(video: Path, fps: float) -> np.ndarray:
    """*video* decoded to gray thumbnails, *fps* of them a second.

    Its black bars are cropped off first, so the thumbnails hold the picture and
    nothing else — a pillarboxed clip and the unpadded scene it came out of are
    the same picture, and have to reach the hash as the same grid of cells.

    Empty when ffmpeg cannot read the file, which leaves that video matching
    nothing rather than stopping the batch. Files with damaged frames do decode,
    complaining on stderr the whole way — held back unless the run really fails,
    since a batch over hundreds of videos is unreadable otherwise.
    """
    crop = content_crop(video)
    filters = [f"fps={fps}"]
    if crop is not None:
        filters.append("crop={}:{}:{}:{}".format(*crop))
    # Averaging the whole source block, rather than sampling a few pixels of it,
    # is what makes a 4K upscale thumbnail like its 540p original.
    filters.append(f"scale={SAMPLE_WIDTH}:{SAMPLE_HEIGHT}:flags=area")
    command = [
        "ffmpeg", "-v", "error", "-i", str(video), "-an",
        "-vf", ",".join(filters),
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


def forget(clip: Path, scene: Path, *, metadata_root: Path) -> None:
    """Drop *clip*'s recorded match, if what it records is *scene*.

    For a file this sweep has just proved is not in *scene* — a match written by
    an earlier run, when the two were taken for one video. Anything else it
    records is left alone: the sweep only ever measured this one scene, and a
    match to some other one is not its to overrule.
    """
    path = sidecar_for(clip, metadata_root)
    if path is None:
        return
    payload = read_sidecar(clip, metadata_root)
    recorded = payload.get("clip")
    if not isinstance(recorded, dict) or recorded.get("full_video") != str(scene):
        return
    recorded.pop("full_video", None)
    recorded.pop("scene_offset", None)
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
    two scenes can turn out to hold one clip; the answer then goes to each
    version of the winning clip that is measurably in that scene too, so it
    holds whichever one is played without being taken on trust.

    *on_scene* is called with each scene and what aligned to it as the sweep
    goes, since it reads every candidate video end to end and takes minutes.
    """
    metas = {entry.video: read_clip(entry.video, metadata_root) for entry in entries}
    # Every clip file is looked for in its own right. Evolver reads a version
    # family off the name, so two different cuts saved as "X" and "X (2)" are one
    # family — and searching for a family rather than a file meant only one
    # member was ever hashed, leaving the other unfindable however exactly its
    # frames sit in a scene. In this library that is what every multi-member clip
    # family turned out to be, so the family saves the sweep almost nothing: 295
    # clips in 286 of them.
    #
    # Scenes still group, by the narrower name-derived family rather than the
    # recorded one, which does not promise a shared timeline: unrelated scenes of
    # a performer land in one recorded group, where the wrong file is decoded and
    # the wrong name gates and only the biggest is ever matched.
    versions = partial(read_version_group, metadata_root=metadata_root)
    clips = [e.video for e in entries if metas[e.video] is not None]
    scenes = group_versions([e for e in entries if metas[e.video] is None], _cut_of)
    # Kept only to carry a settled answer across to a genuine re-encode below.
    families = {
        member.video: family
        for family in group_versions([e for e in entries if metas[e.video] is not None], versions)
        for member in family.members
    }
    hashes: dict[Path, np.ndarray] = {}

    def hashed(video: Path) -> np.ndarray:
        # A clip is a candidate for every scene of its performer, so cache it.
        if video not in hashes:
            hashes[video] = frame_hashes(sampler(video, fps))
        return hashes[video]

    matched: dict[Path, Match] = {}
    for scene_family in scenes:
        scene = _cheapest(scene_family)
        candidates = [
            clip for clip in clips
            if could_be_cut_from(metas[clip], scene_family.canonical.video)
        ]
        found = (
            locate(hashed(scene), {clip: hashed(clip) for clip in candidates}, fps=fps)
            if candidates else None
        )
        if found is not None:
            matched[scene] = found
        if on_scene is not None:
            on_scene(scene, found)

    matched = _best_scene_per_clip(matched)
    for scene, match in matched.items():
        record(match.clip, scene, offset=match.offset, metadata_root=metadata_root)
        # A scene holds one clip, so a genuine re-encode of the winner cannot
        # also win it — it has to be handed the answer to have one at all. But
        # it is asked rather than told, since a family read off the name puts
        # two different cuts in one: telling them filed a clip under a scene it
        # is not in, and gave that scene the wrong clip's funscript. One that
        # really is another encode aligns here too, at its own offset; one that
        # does not is told nothing, and loses what an earlier run told it.
        for member in families[match.clip].members:
            if member.video == match.clip:
                continue
            own = align(hashed(member.video), hashed(scene), fps=fps)
            if own is None:
                forget(member.video, scene, metadata_root=metadata_root)
            else:
                record(member.video, scene, offset=own.offset, metadata_root=metadata_root)
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


def _cut_of(video: Path) -> str | None:
    """Which cut *video* is a version of: its title, less what a version changes.

    None where a name reduces to nothing — all quality tags and hash — so such a
    file stands alone rather than gathering every other one to it.
    """
    return stable_title(video.stem) or None


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
