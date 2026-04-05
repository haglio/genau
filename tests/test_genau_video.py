"""Tests for genau.video."""
from __future__ import annotations

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
