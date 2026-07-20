"""Condemning a clip: out of rotation, into the pile Evolver sweeps.

Genau does the least it can here — one file move.  A clip's other traces (its
decoded ``.rhcache`` in ``frames/``, the clipper session it was cut from, the
source video's metadata) stay where they are, for Evolver to reconcile against
the pile later.  Which clip was condemned is the whole of the state this
leaves, and the filename carries it.
"""
from __future__ import annotations

from pathlib import Path


def weird_dir_for_clips_folder(folder: Path) -> Path:
    """The condemned pile beside a clips folder, as ``frames/`` sits beside it."""
    return folder.parent / "weird"


def move_clip_to_weird(clip_path: Path, weird_dir: Path) -> Path | None:
    """Move *clip_path* into *weird_dir*, returning where it landed.

    Returns None when the clip is already gone — two WEIRD verbs can name the
    same clip before the first has finished, and the second must not take the
    player down with it.
    """
    if not clip_path.exists():
        return None
    weird_dir.mkdir(parents=True, exist_ok=True)
    destination = weird_dir / clip_path.name
    clip_path.replace(destination)
    return destination
