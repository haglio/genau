"""Reading the metadata sidecar Evolver keeps beside every library video.

The metadata tree mirrors the video library one-to-one (``…/videos/metadata``
pairs with ``…/videos/videos``), so a video's record sits at the same path under
the metadata root as the video sits under the library root. Evolver owns what
goes in; Nau only reads, and a missing or malformed file is the ordinary case
rather than an error — plenty of videos predate the metadata.
"""
from __future__ import annotations

import json
from pathlib import Path


def sidecar_for(video: Path, metadata_root: Path) -> Path | None:
    """Where Evolver's metadata for *video* lives, or None if *video* is outside."""
    try:
        rel = video.relative_to(metadata_root.parent / "videos")
    except ValueError:
        return None
    return (metadata_root / rel).with_suffix(".json")


def read_sidecar(video: Path, metadata_root: Path) -> dict:
    """Everything Evolver recorded for *video*; empty when there is nothing."""
    sidecar = sidecar_for(video, metadata_root)
    if sidecar is None:
        return {}
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def read_clip(video: Path, metadata_root: Path) -> dict | None:
    """The ``clip`` object Evolver recorded for *video*, or None.

    Present only on a scene carved out of a compilation: it names the parent
    compilation, the running order within it, and the source movie + performer.
    """
    clip = read_sidecar(video, metadata_root).get("clip")
    return clip if isinstance(clip, dict) else None


def read_version_group(video: Path, metadata_root: Path) -> str | None:
    """The version-family id Evolver recorded for *video*, or None.

    Every re-encode, upscale and hand-renamed variant of one video carries the
    same id, which is what makes it the authority on "same video, other version"
    — the names alone cannot say so (see Evolver's ``NONAI_VERSION_OVERRIDES``).
    None means no record, so the caller falls back to reading the names.
    """
    version = read_sidecar(video, metadata_root).get("version")
    if not isinstance(version, dict):
        return None
    group = version.get("group")
    return str(group) if group else None
