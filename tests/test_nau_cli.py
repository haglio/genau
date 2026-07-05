from __future__ import annotations

import random
from pathlib import Path

from nau.cli import audio_muted, build_parser, library_source, resolve_playlist


class TestResolvePlaylist:
    def test_playlist_file_wins_over_discovery(self, tmp_path):
        playlist = tmp_path / "nau_playlist.tsv"
        vid = tmp_path / "a.mp4"
        vid.write_text("fake")
        playlist.write_text(f"{vid}\n", encoding="utf-8")
        args = build_parser({}).parse_args(["--playlist", str(playlist)])

        pairs = resolve_playlist(args)

        assert pairs == [(vid, None)]

    def test_playlist_file_skips_dedup(self, tmp_path):
        # Explicit Fun Time playlists are returned verbatim — no version folding.
        playlist = tmp_path / "nau_playlist.tsv"
        a = tmp_path / "Asa-540.mp4"
        b = tmp_path / "Asa-1080p.mp4"
        a.write_text("x")
        b.write_text("x")
        playlist.write_text(f"{a}\n{b}\n", encoding="utf-8")
        args = build_parser({}).parse_args(["--playlist", str(playlist)])

        pairs = resolve_playlist(args)

        assert pairs == [(a, None), (b, None)]

    def test_discovery_dedups_and_keeps_full_length(self, tmp_path):
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
        # Standalone defaults to scripted-only (the loop-tool default), so the
        # videos need funscripts to survive; dedup + length still apply.
        big_fs = scripts / "Asa-1080p.funscript"
        big_fs.write_text("{}")
        (scripts / "Asa-540.funscript").write_text("{}")
        (scripts / "teaser-1080p.funscript").write_text("{}")
        args = build_parser({}).parse_args([
            "--videos-dir", str(vids), "--scripts-dir", str(scripts),
        ])
        durations = {big: 300.0, small: 300.0, short: 10.0}

        pairs = resolve_playlist(args, durations=durations, rng=random.Random(0))

        # Short teaser filtered out (full-length default); Asa folded to canonical.
        assert pairs == [(big, big_fs)]

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
