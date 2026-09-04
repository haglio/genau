"""Tests for genau.video."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from genau.video import scan_clips

# ---------------------------------------------------------------------------
# scan_clips
# ---------------------------------------------------------------------------

class TestScanClips:
    def test_finds_mp4_files(self, tmp_path: Path):
        (tmp_path / "a.mp4").touch()
        (tmp_path / "b.mp4").touch()
        result = scan_clips(tmp_path, shuffle_on_load=False)
        names = {p.name for p in result}
        assert names == {"a.mp4", "b.mp4"}

    def test_finds_mixed_extensions(self, tmp_path: Path):
        (tmp_path / "movie.mkv").touch()
        (tmp_path / "clip.mp4").touch()
        result = scan_clips(tmp_path, shuffle_on_load=False)
        assert len(result) == 2

    def test_ignores_non_video_files(self, tmp_path: Path):
        (tmp_path / "video.mp4").touch()
        (tmp_path / "notes.txt").touch()
        (tmp_path / "image.jpg").touch()
        result = scan_clips(tmp_path, shuffle_on_load=False)
        assert len(result) == 1
        assert result[0].name == "video.mp4"

    def test_ignores_subdirectories(self, tmp_path: Path):
        (tmp_path / "video.mp4").touch()
        (tmp_path / "subdir").mkdir()
        result = scan_clips(tmp_path, shuffle_on_load=False)
        assert len(result) == 1

    def test_raises_when_folder_empty(self, tmp_path: Path):
        with pytest.raises(RuntimeError, match="No video clips found"):
            scan_clips(tmp_path)

    def test_raises_when_only_non_video_files(self, tmp_path: Path):
        (tmp_path / "readme.txt").touch()
        with pytest.raises(RuntimeError, match="No video clips found"):
            scan_clips(tmp_path)

    def test_extension_matching_is_case_insensitive(self, tmp_path: Path):
        (tmp_path / "clip.MP4").touch()
        (tmp_path / "other.MKV").touch()
        result = scan_clips(tmp_path, shuffle_on_load=False)
        assert len(result) == 2

    def test_shuffle_off_gives_deterministic_order(self, tmp_path: Path):
        for name in ["c.mp4", "a.mp4", "b.mp4"]:
            (tmp_path / name).touch()
        r1 = scan_clips(tmp_path, shuffle_on_load=False)
        r2 = scan_clips(tmp_path, shuffle_on_load=False)
        assert r1 == r2

    def test_shuffle_on_returns_all_files(self, tmp_path: Path):
        for name in ["x.mp4", "y.mp4", "z.mp4"]:
            (tmp_path / name).touch()
        result = scan_clips(tmp_path, shuffle_on_load=True)
        assert len(result) == 3
        assert {p.name for p in result} == {"x.mp4", "y.mp4", "z.mp4"}


class TestTheShuffleItself:
    """It was a call on a module-global generator with no seed, so the only
    thing a test could say about it was that nothing went missing.  It is a
    dependency now, and these say what it is actually asked to do."""

    @staticmethod
    def _folder(tmp_path: Path) -> Path:
        for name in ("alpha.mp4", "beta.mp4", "gamma.mp4"):
            (tmp_path / name).touch()
        return tmp_path

    def test_the_order_it_leaves_the_list_in_is_the_order_returned(self, tmp_path: Path):
        """It shuffles in place, so a caller that ignored the mutation and
        returned the list it built would come back unshuffled."""
        def _z_to_a(files):
            files.sort(key=lambda path: path.name, reverse=True)

        result = scan_clips(self._folder(tmp_path), shuffle_on_load=True,
                            shuffle=_z_to_a)

        assert [path.name for path in result] == [
            "gamma.mp4", "beta.mp4", "alpha.mp4"]

    def test_it_is_asked_once_and_given_every_clip(self, tmp_path: Path):
        asked = []

        scan_clips(self._folder(tmp_path), shuffle_on_load=True,
                   shuffle=lambda files: asked.append(list(files)))

        assert len(asked) == 1
        assert {path.name for path in asked[0]} == {
            "alpha.mp4", "beta.mp4", "gamma.mp4"}

    def test_it_is_not_asked_when_the_config_says_not_to(self, tmp_path: Path):
        asked = []

        scan_clips(self._folder(tmp_path), shuffle_on_load=False,
                   shuffle=asked.append)

        assert asked == []

    def test_it_is_not_asked_for_an_order_that_was_named_outright(self, tmp_path: Path):
        """Latest is an order; shuffling it would undo it."""
        asked = []

        scan_clips(self._folder(tmp_path), shuffle_on_load=True, recent=True,
                   shuffle=asked.append)

        assert asked == []


class TestLatestOrder:
    """Newest-first — the order "latest" asks for, so a clip that landed in the
    folder minutes ago heads the sequence instead of sitting somewhere in it."""

    @staticmethod
    def _aged(tmp_path: Path, name: str, mtime: float) -> Path:
        path = tmp_path / name
        path.touch()
        os.utime(path, (mtime, mtime))
        return path

    def test_newest_clip_comes_first(self, tmp_path: Path):
        self._aged(tmp_path, "old.mp4", 1_000)
        self._aged(tmp_path, "newest.mp4", 3_000)
        self._aged(tmp_path, "middle.mp4", 2_000)

        result = scan_clips(tmp_path, recent=True)

        assert [path.name for path in result] == ["newest.mp4", "middle.mp4", "old.mp4"]

    def test_the_named_order_outranks_the_shuffle(self, tmp_path: Path):
        """Shuffling an order that was asked for outright would undo it, and
        ``shuffle_on_load`` is a config default rather than this session's word."""
        self._aged(tmp_path, "old.mp4", 1_000)
        self._aged(tmp_path, "new.mp4", 2_000)

        result = scan_clips(tmp_path, shuffle_on_load=True, recent=True)

        assert [path.name for path in result] == ["new.mp4", "old.mp4"]
