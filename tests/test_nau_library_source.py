from __future__ import annotations

import random
from pathlib import Path

from nau.library_source import build_library_source, discover_clips


def _make_video(path: Path, body: str = "x") -> Path:
    path.write_text(body)
    return path


class TestBuildLibrarySource:
    def test_playlist_for_full_and_shorts(self, tmp_path):
        vids = tmp_path / "videos"
        scripts = tmp_path / "scripts"
        vids.mkdir()
        scripts.mkdir()
        long_vid = _make_video(vids / "long-1080p.mp4")
        short_vid = _make_video(vids / "teaser-1080p.mp4")
        durations = {long_vid: 300.0, short_vid: 10.0}

        source = build_library_source(
            vids, scripts, None, rng=random.Random(0), durations=durations, scripted_only=False,
        )

        full = source.playlist_for("full")
        shorts = source.playlist_for("shorts")
        assert [v for v, _ in full] == [long_vid]
        assert [v for v, _ in shorts] == [short_vid]

    def test_shorts_mode_includes_clips_dir(self, tmp_path):
        vids = tmp_path / "videos"
        scripts = tmp_path / "scripts"
        clips = tmp_path / "clips"
        vids.mkdir()
        scripts.mkdir()
        clips.mkdir()
        long_vid = _make_video(vids / "long-1080p.mp4")
        clip = _make_video(clips / "saved.mp4")
        durations = {long_vid: 300.0}

        source = build_library_source(
            vids, scripts, clips, rng=random.Random(0), durations=durations, scripted_only=False,
        )

        shorts_videos = {v for v, _ in source.playlist_for("shorts")}
        assert clip in shorts_videos

    def test_version_index_covers_all_entries(self, tmp_path):
        vids = tmp_path / "videos"
        scripts = tmp_path / "scripts"
        vids.mkdir()
        scripts.mkdir()
        big = _make_video(vids / "Asa-1080p.mp4", body="a bigger body here")
        small = _make_video(vids / "Asa-540.mp4", body="sm")
        durations = {big: 300.0, small: 300.0}

        source = build_library_source(
            vids, scripts, None, rng=random.Random(0), durations=durations,
        )

        # Both versions map to the same ordered pair list (canonical first).
        assert source.version_index[big] == source.version_index[small]
        assert source.version_index[big][0][0] == big

    def test_version_index_includes_clips(self, tmp_path):
        vids = tmp_path / "videos"
        scripts = tmp_path / "scripts"
        clips = tmp_path / "clips"
        vids.mkdir()
        scripts.mkdir()
        clips.mkdir()
        long_vid = _make_video(vids / "long-1080p.mp4")
        clip = _make_video(clips / "saved.mp4")
        durations = {long_vid: 300.0}

        source = build_library_source(
            vids, scripts, clips, rng=random.Random(0), durations=durations,
        )

        assert clip in source.version_index


class TestDiscoverClips:
    def test_absent_dir_is_empty(self, tmp_path):
        assert discover_clips(tmp_path / "nope") == []

    def test_none_dir_is_empty(self):
        assert discover_clips(None) == []

    def test_lists_clip_videos_with_size(self, tmp_path):
        clips = tmp_path / "clips"
        clips.mkdir()
        (clips / "a.mp4").write_text("body")
        (clips / "notes.txt").write_text("ignore me")

        result = discover_clips(clips)

        assert len(result) == 1
        assert result[0].video == clips / "a.mp4"
        assert result[0].funscript is None
        assert result[0].size == len("body")


def test_standalone_source_serves_all_videos_by_default():
    """Standalone Nau is a general player; scripted-focus is Fun Time's
    F-mode, so the default source serves scripted and unscripted alike."""
    import random
    from pathlib import Path
    from nau.library import LibraryEntry
    from nau.library_source import LibrarySource

    scripted = LibraryEntry(video=Path("Gigi-topaz.mp4"), funscript=Path("Gigi.funscript"), size=900)
    unscripted = LibraryEntry(video=Path("Hana-1080p.mp4"), funscript=None, size=900)
    src = LibrarySource(
        entries=[scripted, unscripted], clips=[],
        durations={scripted.video: 300.0, unscripted.video: 300.0},
        rng=random.Random(0),
    )

    vids = {v for v, _ in src.playlist_for("full")}

    assert scripted.video in vids and unscripted.video in vids
    assert src.scripted_only is False
