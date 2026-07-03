from __future__ import annotations

from nau.playlist import read_playlist


class TestReadPlaylist:
    def test_parses_video_and_funscript_pairs(self, tmp_path):
        playlist = tmp_path / "nau_playlist.tsv"
        playlist.write_text(
            "C:/vids/a.mp4\tC:/scripts/a.funscript\n"
            "C:/vids/b.mp4\t\n"
            "C:/vids/c.mp4\n",
            encoding="utf-8",
        )

        result = read_playlist(playlist)

        assert [str(v) for v, _ in result] == [
            "C:\\vids\\a.mp4", "C:\\vids\\b.mp4", "C:\\vids\\c.mp4",
        ]
        assert str(result[0][1]) == "C:\\scripts\\a.funscript"
        assert result[1][1] is None
        assert result[2][1] is None

    def test_skips_blank_and_comment_lines(self, tmp_path):
        playlist = tmp_path / "nau_playlist.tsv"
        playlist.write_text(
            "# header comment\n"
            "\n"
            "C:/vids/a.mp4\tC:/scripts/a.funscript\n",
            encoding="utf-8",
        )

        result = read_playlist(playlist)

        assert len(result) == 1

    def test_missing_file_returns_empty(self, tmp_path):
        assert read_playlist(tmp_path / "nope.tsv") == []
