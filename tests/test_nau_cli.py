from __future__ import annotations

from nau.cli import build_parser, resolve_playlist


class TestResolvePlaylist:
    def test_playlist_file_wins_over_discovery(self, tmp_path):
        playlist = tmp_path / "nau_playlist.tsv"
        vid = tmp_path / "a.mp4"
        vid.write_text("fake")
        playlist.write_text(f"{vid}\n", encoding="utf-8")
        args = build_parser({}).parse_args(["--playlist", str(playlist)])

        pairs = resolve_playlist(args)

        assert pairs == [(vid, None)]

    def test_falls_back_to_discovery(self, tmp_path):
        vids = tmp_path / "videos"
        scripts = tmp_path / "scripts"
        vids.mkdir()
        scripts.mkdir()
        (vids / "clip.mp4").write_text("fake")
        args = build_parser({}).parse_args([
            "--videos-dir", str(vids), "--scripts-dir", str(scripts),
        ])

        pairs = resolve_playlist(args)

        assert pairs == [(vids / "clip.mp4", None)]

    def test_no_sources_returns_empty(self):
        args = build_parser({}).parse_args([])

        assert resolve_playlist(args) == []
