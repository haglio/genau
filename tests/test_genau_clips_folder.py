"""Which clips Genau plays out of the clips folder it is given, and where a condemned one goes."""
from __future__ import annotations

import logging
from pathlib import Path

from genau.app import _condemn_clip, _played_clips


def _clips_folder(root: Path, *places: str) -> Path:
    clips = root / "clips"
    for place in places:
        (clips / place).parent.mkdir(parents=True, exist_ok=True)
        (clips / place).write_bytes(b"clip")
    return clips


def test_genau_plays_every_2d_clip_and_no_vr_clip(tmp_path: Path):
    clips = _clips_folder(tmp_path, "2D/AI/loop one.mp4", "2D/non_AI/scene one.mp4",
                          "VR/scene two_180.mp4")

    played = _played_clips(clips, shuffle_on_load=False, recent=False)

    assert sorted(played) == [clips / "2D" / "AI" / "loop one.mp4",
                              clips / "2D" / "non_AI" / "scene one.mp4"]


def test_a_condemned_clip_goes_to_its_own_place_in_the_weird_pile(tmp_path: Path):
    clips = _clips_folder(tmp_path, "2D/non_AI/scene one.mp4")

    _condemn_clip(clips / "2D" / "non_AI" / "scene one.mp4", clips, logging.getLogger(__name__))

    assert (tmp_path / "weird" / "2D" / "non_AI" / "scene one.mp4").read_bytes() == b"clip"
    assert not (clips / "2D" / "non_AI" / "scene one.mp4").exists()
