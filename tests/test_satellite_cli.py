from __future__ import annotations

from pathlib import Path

from satellite.cli import audio_muted, build_parser, resolve_playlist


def test_resolve_playlist_reads_videos_dropping_funscripts(tmp_path):
    pl = tmp_path / "portrait.tsv"
    pl.write_text("a.mp4\nb.mp4\tb.funscript\n", encoding="utf-8")
    args = build_parser().parse_args(["--playlist", str(pl)])

    assert resolve_playlist(args) == [Path("a.mp4"), Path("b.mp4")]


def test_resolve_playlist_without_a_file_is_empty(tmp_path):
    args = build_parser().parse_args([])
    assert resolve_playlist(args) == []


def test_audio_muted_from_the_flag(tmp_path):
    assert audio_muted(build_parser().parse_args(["--no-audio"])) is True
    assert audio_muted(build_parser().parse_args([])) is False


def test_audio_muted_from_the_env_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("FUN_TIME_MUTE_AUDIO", "1")
    assert audio_muted(build_parser().parse_args([])) is True


def test_parser_accepts_the_file_quartet_and_geometry(tmp_path):
    args = build_parser().parse_args([
        "--playlist", str(tmp_path / "p.tsv"),
        "--command-file", str(tmp_path / "cmd.txt"),
        "--paused-file", str(tmp_path / "paused.txt"),
        "--status-file", str(tmp_path / "status.txt"),
        "--x", "2560", "--y", "0", "--width", "1440", "--height", "2500",
    ])
    assert args.command_file == tmp_path / "cmd.txt"
    assert args.paused_file == tmp_path / "paused.txt"
    assert args.status_file == tmp_path / "status.txt"
    assert (args.x, args.y, args.width, args.height) == (2560, 0, 1440, 2500)
