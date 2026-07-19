from __future__ import annotations

import random
from pathlib import Path

import pytest

from nau.duration_cache import DurationCache
from nau.library import FULL, MIXED, SHORTS
from nau.library_source import (
    DEFAULT_MODE,
    PHASE_DISCOVER,
    PHASE_DURATIONS,
    build_library_source,
    discover_clips,
    next_length_mode,
)


class TestLengthModeCycle:
    def test_the_player_opens_unfiltered(self):
        """Fun Time's own playlist has always been every video shuffled, so a
        player that opened claiming a length was claiming one it did not have."""
        assert DEFAULT_MODE == MIXED

    def test_the_toggle_walks_all_three_and_comes_back(self):
        assert next_length_mode(MIXED) == SHORTS
        assert next_length_mode(SHORTS) == FULL
        assert next_length_mode(FULL) == MIXED

    def test_an_unknown_mode_lands_on_the_default(self):
        """Nothing sets one, but the toggle must land somewhere real rather than
        raise into the run loop."""
        assert next_length_mode("") == DEFAULT_MODE


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


class TestBuildProgress:
    """Startup's only long wait is probing durations, so the build reports it."""

    def test_reports_each_probed_entry_against_the_total(self, tmp_path):
        vids = tmp_path / "videos"
        scripts = tmp_path / "scripts"
        vids.mkdir()
        scripts.mkdir()
        for name in ("a.mp4", "b.mp4", "c.mp4"):
            _make_video(vids / name)
        seen: list[tuple[str, int, int]] = []

        build_library_source(
            vids, scripts, None, rng=random.Random(0),
            duration_cache=DurationCache(tmp_path / "cache.json", prober=lambda p: 300.0),
            on_progress=lambda phase, done, total: seen.append((phase, done, total)),
        )

        assert (PHASE_DISCOVER, 0, 0) in seen
        assert [s for s in seen if s[0] == PHASE_DURATIONS] == [
            (PHASE_DURATIONS, 0, 3), (PHASE_DURATIONS, 1, 3), (PHASE_DURATIONS, 2, 3),
        ]

    def test_a_raising_callback_stops_the_probing(self, tmp_path):
        """Closing the window mid-probe has to end the wait, not be noticed once
        it is over — so the callback aborts the build by raising."""
        vids = tmp_path / "videos"
        scripts = tmp_path / "scripts"
        vids.mkdir()
        scripts.mkdir()
        for name in ("a.mp4", "b.mp4", "c.mp4"):
            _make_video(vids / name)
        probed: list[Path] = []

        class GaveUp(Exception):
            """Whatever the caller raises — the build has no opinion on it."""

        def give_up(phase, done, total):
            if phase == PHASE_DURATIONS and done == 1:
                raise GaveUp

        with pytest.raises(GaveUp):
            build_library_source(
                vids, scripts, None, rng=random.Random(0),
                duration_cache=DurationCache(
                    tmp_path / "cache.json", prober=lambda p: probed.append(p) or 300.0,
                ),
                on_progress=give_up,
            )

        assert len(probed) == 1  # stopped at the raise, not after all three


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


def test_version_index_groups_by_metadata_sidecar_when_metadata_root_set(tmp_path):
    import json
    import random
    from nau.library import LibraryEntry
    from nau.library_source import LibrarySource, read_version_group

    lib = tmp_path / "videos" / "videos"
    meta = tmp_path / "videos" / "metadata"
    original = lib / "winston" / "2_orig" / "Scene-One-abc.mkv"
    upscale = lib / "winston" / "3_done" / "wholly-different-name_apo8_iris2.mp4"
    for clip, size in ((original, 100), (upscale, 900)):
        clip.parent.mkdir(parents=True, exist_ok=True)
        clip.write_bytes(b"x")
        side = (meta / clip.relative_to(lib)).with_suffix(".json")
        side.parent.mkdir(parents=True, exist_ok=True)
        side.write_text(
            json.dumps({"version": {"group": "winston/Scene-One-abc", "processed": clip is upscale}}),
            encoding="utf-8",
        )
    ea = LibraryEntry(video=original, funscript=None, size=100)
    eb = LibraryEntry(video=upscale, funscript=None, size=900)
    source = LibrarySource(
        entries=[ea, eb], clips=[], durations={original: 300.0, upscale: 300.0},
        rng=random.Random(0), metadata_root=meta,
    )

    index = source.version_index

    assert index[original] == index[upscale]  # folded despite unrelated names
    assert index[original][0][0] == upscale  # canonical is the larger clip
    assert read_version_group(original, meta) == "winston/Scene-One-abc"


def test_version_index_falls_back_to_names_without_a_metadata_root(tmp_path):
    import random
    from nau.library import LibraryEntry
    from nau.library_source import LibrarySource

    a = LibraryEntry(video=Path("Mya.mp4"), funscript=None, size=50)
    b = LibraryEntry(video=Path("Mya_topaz.mp4"), funscript=None, size=800)
    source = LibrarySource(
        entries=[a, b], clips=[], durations={a.video: 300.0, b.video: 300.0},
        rng=random.Random(0),
    )

    assert source.version_index[a.video] == source.version_index[b.video]
