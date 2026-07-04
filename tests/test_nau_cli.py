from __future__ import annotations

import random
from pathlib import Path

from nau.cli import audio_muted, build_parser, resolve_playlist


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
        args = build_parser({}).parse_args([
            "--videos-dir", str(vids), "--scripts-dir", str(scripts),
        ])
        durations = {big: 300.0, small: 300.0, short: 10.0}

        pairs = resolve_playlist(args, durations=durations, rng=random.Random(0))

        # Short teaser filtered out (full-length default); Asa folded to canonical.
        assert pairs == [(big, None)]

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
