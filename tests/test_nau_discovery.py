from __future__ import annotations

from nau.discovery import discover_videos


class TestDiscoverVideos:
    def test_discovers_video_with_matching_funscript(self, tmp_path):
        vids = tmp_path / "videos"
        scripts = tmp_path / "scripts"
        vids.mkdir()
        scripts.mkdir()
        (vids / "clip.mp4").write_text("fake")
        (scripts / "clip.funscript").write_text("{}")

        result = discover_videos(vids, scripts)

        assert len(result) == 1
        assert result[0][0] == vids / "clip.mp4"
        assert result[0][1] == scripts / "clip.funscript"

    def test_skips_video_without_funscript(self, tmp_path):
        vids = tmp_path / "videos"
        scripts = tmp_path / "scripts"
        vids.mkdir()
        scripts.mkdir()
        (vids / "clip.mp4").write_text("fake")

        result = discover_videos(vids, scripts)

        assert result == []

    def test_handles_subdirectories(self, tmp_path):
        vids = tmp_path / "videos" / "sub"
        scripts = tmp_path / "scripts" / "sub"
        vids.mkdir(parents=True)
        scripts.mkdir(parents=True)
        (vids / "deep.mkv").write_text("fake")
        (scripts / "deep.funscript").write_text("{}")

        result = discover_videos(vids.parent, scripts.parent)

        assert len(result) == 1

    def test_empty_directory(self, tmp_path):
        vids = tmp_path / "videos"
        scripts = tmp_path / "scripts"
        vids.mkdir()
        scripts.mkdir()

        result = discover_videos(vids, scripts)

        assert result == []
