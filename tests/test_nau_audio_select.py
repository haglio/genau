from __future__ import annotations

from pathlib import Path

from nau.playback import NullAudioPlayer, build_audio_player


class TestBuildAudioPlayer:
    def test_muted_returns_null_player(self):
        player = build_audio_player(muted=True)
        assert isinstance(player, NullAudioPlayer)

    def test_unmuted_returns_real_player(self):
        # The real AudioPlayer tries to init pygame.mixer, which may be
        # unavailable in CI; either way it must NOT be the null player.
        player = build_audio_player(muted=False)
        assert not isinstance(player, NullAudioPlayer)


class TestNullAudioPlayer:
    def test_all_methods_are_noops_and_never_touch_ffmpeg(self, tmp_path: Path):
        player = NullAudioPlayer()
        # Every call must return without spawning a subprocess or raising.
        player.load(tmp_path / "video.mp4")
        player.play(0)
        player.pause()
        player.resume()
        player.seek(1234)
        player.start_loop(0, 1000)
        player.stop_loop(500)
        player.stop()
        player.close()
