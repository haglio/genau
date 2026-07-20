from __future__ import annotations

from pathlib import Path

from genau.weird import move_clip_to_weird, weird_dir_for_clips_folder


def test_weird_dir_sits_beside_the_clips_folder():
    assert weird_dir_for_clips_folder(Path("C:/videos/genau/clips")) == Path(
        "C:/videos/genau/weird"
    )


def test_move_takes_the_clip_out_of_rotation(tmp_path: Path):
    clips = tmp_path / "clips"
    clips.mkdir()
    clip = clips / "odd.mp4"
    clip.write_bytes(b"clip")
    weird = tmp_path / "weird"

    landed = move_clip_to_weird(clip, weird)

    assert landed == weird / "odd.mp4"
    assert landed.read_bytes() == b"clip"
    assert not clip.exists()


def test_move_creates_the_weird_dir_on_first_use(tmp_path: Path):
    clip = tmp_path / "odd.mp4"
    clip.write_bytes(b"clip")
    weird = tmp_path / "weird"
    assert not weird.exists()

    move_clip_to_weird(clip, weird)

    assert weird.is_dir()


def test_a_clip_already_gone_is_not_an_error(tmp_path: Path):
    """Two WEIRD verbs can race the same clip; the second must not crash Genau."""
    weird = tmp_path / "weird"

    assert move_clip_to_weird(tmp_path / "missing.mp4", weird) is None
