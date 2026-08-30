from __future__ import annotations

import random
from pathlib import Path

import pytest

from nau.cli import (
    audio_muted,
    build_parser,
    library_source,
    mode_memory,
    resolve_playlist,
)
from nau.library import SHORTS
from nau.library_source import PHASE_DISCOVER
from nau.mode_memory import RememberedMode


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
        a = tmp_path / "Jane-540.mp4"
        b = tmp_path / "Jane-1080p.mp4"
        a.write_text("x")
        b.write_text("x")
        playlist.write_text(f"{a}\n{b}\n", encoding="utf-8")
        args = build_parser({}).parse_args(["--playlist", str(playlist)])

        pairs = resolve_playlist(args)

        assert pairs == [(a, None), (b, None)]

    def test_playlist_file_collapses_versions_with_a_source(self, tmp_path):
        # Fun Time lists both an original and its upscale; the source's version
        # groups fold them to one slot — the larger — matching the rotation the
        # main player shows and the set "cycle version" walks.
        vids = tmp_path / "videos"
        scripts = tmp_path / "scripts"
        vids.mkdir()
        scripts.mkdir()
        original = vids / "Jane-540.mp4"
        upscale = vids / "Jane-540_topaz.mp4"
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
        big = vids / "Jane-1080p.mp4"
        small = vids / "Jane-540.mp4"
        short = vids / "teaser-1080p.mp4"
        big.write_text("a much bigger body")  # canonical
        small.write_text("sm")
        short.write_text("teaser")
        big_fs = scripts / "Jane-1080p.funscript"
        big_fs.write_text("{}")
        (scripts / "Jane-540.funscript").write_text("{}")
        (scripts / "teaser-1080p.funscript").write_text("{}")
        args = build_parser({}).parse_args([
            "--videos-dir", str(vids), "--scripts-dir", str(scripts),
        ])
        durations = {big: 300.0, small: 300.0, short: 10.0}

        pairs = resolve_playlist(args, durations=durations, rng=random.Random(0))

        # Jane folded to its canonical (largest) version; the teaser survives,
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


class TestBorderless:
    def test_borderless_is_off_by_default_and_on_by_flag(self):
        """Standalone keeps its chrome; Fun Time passes --borderless to drop it."""
        assert build_parser({}).parse_args([]).borderless is False
        assert build_parser({}).parse_args(["--borderless"]).borderless is True


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


# The command line Fun Time builds for `python -m nau`, flag for flag, with
# fabricated paths.  argparse exits 2 on any flag it does not know, so a rename
# on either side of this list is a player that will not launch under Fun Time --
# and the list is written out here rather than derived so the rename shows up as
# a diff in both repos.
FUN_TIME_ARGV = [
    "--config", "C:/example/genau_config.json",
    "--playlist", "C:/example/state/nau_playlist.tsv",
    "--command-file", "C:/example/state/nau_cmd.txt",
    "--paused-file", "C:/example/state/nau_paused.txt",
    "--status-file", "C:/example/state/nau_status.txt",
    "--console-file", "C:/example/state/console.json",
    "--drive-file", "C:/example/state/drive.txt",
    "--dashboard-cmd-file", "C:/example/state/dashboard_cmd.txt",
    "--x", "1920",
    "--y", "0",
    "--width", "1280",
    "--height", "1024",
    "--borderless",
    "--taskbar-identity", "Example.Orchestrator",
    "--metadata-dir", "C:/example/library/metadata",
]

# What each of those has to land as.  The type matters as much as the value:
# a Path flag that came through as a str reaches Path(...) somewhere later and
# a str flag that came through as a Path reaches an argparse default nobody set.
LANDS_AS = {
    "config": Path("C:/example/genau_config.json"),
    "playlist": Path("C:/example/state/nau_playlist.tsv"),
    "command_file": Path("C:/example/state/nau_cmd.txt"),
    "paused_file": Path("C:/example/state/nau_paused.txt"),
    "status_file": Path("C:/example/state/nau_status.txt"),
    "console_file": Path("C:/example/state/console.json"),
    "drive_file": Path("C:/example/state/drive.txt"),
    "dashboard_cmd_file": Path("C:/example/state/dashboard_cmd.txt"),
    "metadata_dir": Path("C:/example/library/metadata"),
    "x": 1920,
    "y": 0,
    "width": 1280,
    "height": 1024,
    "borderless": True,
    "taskbar_identity": "Example.Orchestrator",
}


class TestTheCommandLineFunTimeLaunchesNauWith:
    @pytest.mark.parametrize("name, expected", sorted(LANDS_AS.items()))
    def test_each_flag_lands_on_the_namespace_as_itself(self, name, expected):
        args = build_parser({}).parse_args(FUN_TIME_ARGV)

        landed = getattr(args, name)

        assert landed == expected
        assert type(landed) is type(expected), f"--{name.replace('_', '-')} changed type"

    def test_the_whole_line_parses_without_argparse_walking_out(self):
        """argparse exits 2 on an unknown flag, and a player that exits 2 under
        Fun Time never opens its window for the orchestrator to wait on."""
        assert build_parser({}).parse_args(FUN_TIME_ARGV) is not None

    def test_metadata_dir_is_optional_and_the_rest_still_parses(self):
        """Fun Time appends it only when the library has a sidecar root."""
        without = [a for a in FUN_TIME_ARGV
                   if a not in ("--metadata-dir", "C:/example/library/metadata")]

        args = build_parser({}).parse_args(without)

        assert args.metadata_dir is None


class TestTheStandaloneFlags:
    """What Nau's own shortcut passes, which Fun Time never does."""

    @pytest.mark.parametrize("option", ["taskbar_identity", "notice_file"])
    def test_the_parser_always_defines_what_the_app_reads_off_it(self, option):
        """nau/app.py reads both straight off the namespace.

        It used to reach them through `getattr(args, ..., None)`, defending
        against a namespace this parser cannot produce -- which reads as a
        real possibility and is a branch nobody can write a test for. The
        parser is what makes the plain attribute safe, so the parser is what
        is pinned.
        """
        args = build_parser({}).parse_args([])

        assert hasattr(args, option)

    def test_the_library_directories_and_the_silent_run(self, tmp_path):
        args = build_parser({}).parse_args([
            "--videos-dir", str(tmp_path / "videos"),
            "--scripts-dir", str(tmp_path / "scripts"),
            "--clips-dir", str(tmp_path / "clips"),
            "--state-dir", str(tmp_path / "state"),
            "--notice-file", str(tmp_path / "notice.txt"),
            "--no-audio",
        ])

        assert args.videos_dir == tmp_path / "videos"
        assert args.scripts_dir == tmp_path / "scripts"
        assert args.clips_dir == tmp_path / "clips"
        assert args.state_dir == tmp_path / "state"
        assert args.notice_file == tmp_path / "notice.txt"
        assert audio_muted(args) is True


class TestTheConfigsOwnDefaults:
    """The nau section of the config stands in for flags nobody passes."""

    CONFIG = {
        "clips_dir": "C:/example/library/clips",
        "state_dir": "C:/example/state",
        "nau": {
            "videos_dir": "C:/example/library/videos",
            "scripts_dir": "C:/example/library/scripts",
            "metadata_dir": "C:/example/library/metadata",
            "notice_file": "C:/example/state/notice.txt",
            "tcode_udp_host": "10.0.0.7",
            "tcode_udp_port": 51000,
        },
    }

    @pytest.mark.parametrize("name, expected", [
        ("videos_dir", Path("C:/example/library/videos")),
        ("scripts_dir", Path("C:/example/library/scripts")),
        ("metadata_dir", Path("C:/example/library/metadata")),
        ("notice_file", Path("C:/example/state/notice.txt")),
        ("clips_dir", Path("C:/example/library/clips")),
        ("state_dir", Path("C:/example/state")),
        ("tcode_host", "10.0.0.7"),
        ("tcode_port", 51000),
    ])
    def test_a_configured_value_is_what_the_flag_would_have_said(self, name, expected):
        args = build_parser(self.CONFIG).parse_args([])

        assert getattr(args, name) == expected

    def test_the_device_defaults_to_the_port_the_family_listens_on(self):
        """50557 is the broker's, and Genau's, and GenauVR's."""
        args = build_parser({}).parse_args([])

        assert (args.tcode_host, args.tcode_port) == ("127.0.0.1", 50557)

    def test_a_flag_beats_the_configured_value(self):
        args = build_parser(self.CONFIG).parse_args(["--tcode-port", "50999"])

        assert args.tcode_port == 50999

    def test_the_clips_dir_falls_back_to_the_shared_one(self):
        """Nau's own section may not name one, and the library's top-level
        clips_dir is what every app in the family reads."""
        args = build_parser({"clips_dir": "C:/example/library/clips"}).parse_args([])

        assert args.clips_dir == Path("C:/example/library/clips")


class TestWhereNauKeepsItsState:
    def test_the_state_dir_holds_the_mode_it_was_last_in(self, tmp_path):
        args = build_parser({}).parse_args(["--state-dir", str(tmp_path)])

        mode_memory(args).write(RememberedMode(length_mode=SHORTS))

        assert (tmp_path / "nau_mode.txt").exists()

    def test_with_no_state_dir_it_falls_back_beside_its_config(self, tmp_path):
        """Standalone there is no orchestrator to hand one, and writing into the
        working directory would put it wherever the shortcut was started from."""
        config = tmp_path / "genau_config.json"
        config.write_text("{}", encoding="utf-8")
        args = build_parser({}).parse_args(["--config", str(config)])

        mode_memory(args).write(RememberedMode(length_mode=SHORTS))

        assert (tmp_path / "nau_mode.txt").exists()
