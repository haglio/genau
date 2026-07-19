from __future__ import annotations

import random
from pathlib import Path

from nau.cli import audio_muted, build_parser, library_source, resolve_playlist
from nau.library import SHORTS
from nau.library_source import PHASE_DISCOVER


class TestResolvePlaylist:
    def test_playlist_file_wins_over_discovery(self, tmp_path):
        playlist = tmp_path / "nau_playlist.tsv"
        vid = tmp_path / "a.mp4"
        vid.write_text("fake")
        playlist.write_text(f"{vid}\n", encoding="utf-8")
        args = build_parser({}).parse_args(["--playlist", str(playlist)])

        pairs = resolve_playlist(args)

        assert pairs == [(vid, None)]

    def test_playlist_file_verbatim_without_a_source(self, tmp_path):
        # With no library dirs there is no version grouping to apply, so the
        # explicit playlist is returned as-is.
        playlist = tmp_path / "nau_playlist.tsv"
        a = tmp_path / "Asa-540.mp4"
        b = tmp_path / "Asa-1080p.mp4"
        a.write_text("x")
        b.write_text("x")
        playlist.write_text(f"{a}\n{b}\n", encoding="utf-8")
        args = build_parser({}).parse_args(["--playlist", str(playlist)])

        pairs = resolve_playlist(args)

        assert pairs == [(a, None), (b, None)]

    def test_playlist_file_collapses_versions_with_a_source(self, tmp_path):
        # Fun Time lists both an original and its upscale; the source's version
        # groups fold them to one slot — the larger — matching the rotation the
        # primary player shows and the set "cycle version" walks.
        vids = tmp_path / "videos"
        scripts = tmp_path / "scripts"
        vids.mkdir()
        scripts.mkdir()
        original = vids / "Asa-540.mp4"
        upscale = vids / "Asa-540_topaz.mp4"
        original.write_text("sm")
        upscale.write_text("a much larger body")  # canonical (bigger)
        playlist = tmp_path / "nau_playlist.tsv"
        playlist.write_text(f"{original}\n{upscale}\n", encoding="utf-8")
        args = build_parser({}).parse_args([
            "--playlist", str(playlist),
            "--videos-dir", str(vids), "--scripts-dir", str(scripts),
        ])
        source = library_source(args, durations={original: 300.0, upscale: 300.0})

        pairs = resolve_playlist(args, source=source)

        assert pairs == [(upscale, None)]

    def test_discovery_dedups_versions_and_applies_no_length_filter(self, tmp_path):
        vids = tmp_path / "videos"
        scripts = tmp_path / "scripts"
        vids.mkdir()
        scripts.mkdir()
        big = vids / "Asa-1080p.mp4"
        small = vids / "Asa-540.mp4"
        short = vids / "teaser-1080p.mp4"
        big.write_text("a much bigger body")  # canonical
        small.write_text("sm")
        short.write_text("teaser")
        big_fs = scripts / "Asa-1080p.funscript"
        big_fs.write_text("{}")
        (scripts / "Asa-540.funscript").write_text("{}")
        (scripts / "teaser-1080p.funscript").write_text("{}")
        args = build_parser({}).parse_args([
            "--videos-dir", str(vids), "--scripts-dir", str(scripts),
        ])
        durations = {big: 300.0, small: 300.0, short: 10.0}

        pairs = resolve_playlist(args, durations=durations, rng=random.Random(0))

        # Asa folded to its canonical (largest) version; the teaser survives,
        # because the mode the player opens in applies no length filter.
        assert sorted(video for video, _fs in pairs) == sorted([big, short])
        assert (big, big_fs) in pairs

    def test_discovery_builds_for_the_mode_it_is_given(self, tmp_path):
        """Startup resumes the mode the last session closed in, so the playlist
        it builds has to be that mode's, not always the default."""
        vids = tmp_path / "videos"
        scripts = tmp_path / "scripts"
        vids.mkdir()
        scripts.mkdir()
        long_vid = vids / "feature-1080p.mp4"
        short = vids / "teaser-1080p.mp4"
        long_vid.write_text("x")
        short.write_text("x")
        args = build_parser({}).parse_args([
            "--videos-dir", str(vids), "--scripts-dir", str(scripts),
        ])
        durations = {long_vid: 300.0, short: 10.0}

        pairs = resolve_playlist(
            args, durations=dict(durations), rng=random.Random(0), mode=SHORTS)

        assert [video for video, _fs in pairs] == [short]

    def test_discovery_deterministic_with_seed(self, tmp_path):
        vids = tmp_path / "videos"
        scripts = tmp_path / "scripts"
        vids.mkdir()
        scripts.mkdir()
        for i in range(5):
            (vids / f"v{i}-1080p.mp4").write_text("x")
        args = build_parser({}).parse_args([
            "--videos-dir", str(vids), "--scripts-dir", str(scripts),
        ])
        durations = {vids / f"v{i}-1080p.mp4": 300.0 for i in range(5)}

        a = resolve_playlist(args, durations=dict(durations), rng=random.Random(7))
        b = resolve_playlist(args, durations=dict(durations), rng=random.Random(7))
        assert a == b

    def test_no_sources_returns_empty(self):
        args = build_parser({}).parse_args([])

        assert resolve_playlist(args) == []


class TestLibrarySource:
    def test_none_without_dirs(self):
        args = build_parser({}).parse_args([])
        assert library_source(args) is None

    def test_built_from_dirs(self, tmp_path):
        vids = tmp_path / "videos"
        scripts = tmp_path / "scripts"
        vids.mkdir()
        scripts.mkdir()
        vid = vids / "a-1080p.mp4"
        vid.write_text("x")
        args = build_parser({}).parse_args([
            "--videos-dir", str(vids), "--scripts-dir", str(scripts),
        ])
        assert library_source(args, durations={vid: 300.0}) is not None

    def test_built_even_when_playlist_given(self, tmp_path):
        """Fun Time passes --playlist for its own selection, but Nau still needs
        the source so cycle-version and length-mode work in Fun Time too."""
        vids = tmp_path / "videos"
        scripts = tmp_path / "scripts"
        vids.mkdir()
        scripts.mkdir()
        vid = vids / "a-1080p.mp4"
        vid.write_text("x")
        playlist = tmp_path / "nau_playlist.tsv"
        playlist.write_text(f"{vid}\n", encoding="utf-8")
        args = build_parser({}).parse_args([
            "--playlist", str(playlist),
            "--videos-dir", str(vids), "--scripts-dir", str(scripts),
        ])
        assert library_source(args, durations={vid: 300.0}) is not None

    def test_forwards_progress_to_the_build(self, tmp_path):
        """The loading screen hangs off this callback, so a source built without
        forwarding it leaves the window frozen for the whole wait."""
        vids = tmp_path / "videos"
        scripts = tmp_path / "scripts"
        vids.mkdir()
        scripts.mkdir()
        vid = vids / "a-1080p.mp4"
        vid.write_text("x")
        args = build_parser({}).parse_args([
            "--videos-dir", str(vids), "--scripts-dir", str(scripts),
        ])
        seen = []

        library_source(
            args, durations={vid: 300.0},
            on_progress=lambda phase, done, total: seen.append(phase),
        )

        assert PHASE_DISCOVER in seen

    def test_clips_dir_falls_back_to_top_level_config(self, tmp_path):
        """Fun Time's config has no nau.clips_dir; shorts should still pick up
        the saved clips from the top-level clips_dir the clipper writes to."""
        clips = tmp_path / "clips"
        args = build_parser({"clips_dir": str(clips)}).parse_args([])
        assert args.clips_dir == clips


class TestAudioMuted:
    def test_default_is_unmuted(self, monkeypatch):
        monkeypatch.delenv("FUN_TIME_MUTE_AUDIO", raising=False)
        args = build_parser({}).parse_args([])
        assert audio_muted(args) is False

    def test_no_audio_flag_mutes(self, monkeypatch):
        monkeypatch.delenv("FUN_TIME_MUTE_AUDIO", raising=False)
        args = build_parser({}).parse_args(["--no-audio"])
        assert audio_muted(args) is True

    def test_env_mutes(self, monkeypatch):
        monkeypatch.setenv("FUN_TIME_MUTE_AUDIO", "1")
        args = build_parser({}).parse_args([])
        assert audio_muted(args) is True
