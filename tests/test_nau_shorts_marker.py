from __future__ import annotations

import json
import random
from pathlib import Path

from nau.library import LibraryEntry
from nau.library_source import LibrarySource


def _clip_entry(lib: Path, meta: Path, rel: str) -> LibraryEntry:
    v = lib / rel
    v.parent.mkdir(parents=True, exist_ok=True)
    v.write_bytes(b"x")
    side = (meta / v.relative_to(lib)).with_suffix(".json")
    side.parent.mkdir(parents=True, exist_ok=True)
    side.write_text(json.dumps({"clip": {"compilation": "Vol6", "index": 9,
                                         "source": "POV Scene 2", "performer": "Ann Bly"}}))
    return LibraryEntry(video=v, funscript=None, size=100)


def _plain_entry(lib: Path, rel: str) -> LibraryEntry:
    v = lib / rel
    v.parent.mkdir(parents=True, exist_ok=True)
    v.write_bytes(b"x")
    return LibraryEntry(video=v, funscript=None, size=100)


def _source(tmp_path, durations):
    lib, meta = tmp_path / "videos" / "videos", tmp_path / "videos" / "metadata"
    return lib, meta


def test_a_carved_scene_is_a_short_before_evolver_records_its_kind(tmp_path):
    """The ``clip`` record was how a carved scene was known before there was a
    kind to write, and a library Evolver has not been over since still has only
    that — so it is still read."""
    lib, meta = tmp_path / "videos" / "videos", tmp_path / "videos" / "metadata"
    clip = _clip_entry(lib, meta, "larkin/1 clips/Ann Bly - POV Scene 2.mp4")
    plain = _plain_entry(lib, "larkin/0/Long Movie.mp4")
    src = LibrarySource(
        entries=[clip, plain], clips=[],
        durations={clip.video: 120.0, plain.video: 120.0},  # both well over the short cutoff
        rng=random.Random(0), metadata_root=meta,
    )

    shorts = {v for v, _ in src.playlist_for("shorts")}
    full = {v for v, _ in src.playlist_for("full")}

    assert clip.video in shorts       # the carved 120s scene surfaces as a short
    assert clip.video not in full     # ...and never as full-length
    assert plain.video in full        # a plain 120s is full-length
    assert plain.video not in shorts


def test_without_metadata_root_length_only(tmp_path):
    lib = tmp_path / "videos" / "videos"
    long_plain = _plain_entry(lib, "a/Long.mp4")
    src = LibrarySource(
        entries=[long_plain], clips=[], durations={long_plain.video: 120.0},
        rng=random.Random(0),
    )
    assert long_plain.video in {v for v, _ in src.playlist_for("full")}
    assert long_plain.video not in {v for v, _ in src.playlist_for("shorts")}
