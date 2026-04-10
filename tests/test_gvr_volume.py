"""Tests for GenauVR audio volume control."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from genau_vr.app import AudioPlayer
from genau_vr.playback import PlaybackEngine
from genau_vr.runtime_commands import apply_runtime_command
from genau_vr.voice import VOICE_COMMANDS


class TestAudioPlayerVolume:
    def test_initial_volume_is_quarter(self):
        player = AudioPlayer()

        assert player._volume == 0.25

    def test_adjust_volume_increases(self):
        player = AudioPlayer()

        player.adjust_volume(0.1)

        assert player._volume == 0.35

    def test_adjust_volume_decreases(self):
        player = AudioPlayer()

        player.adjust_volume(-0.1)

        assert player._volume == 0.15

    def test_adjust_volume_clamps_at_one(self):
        player = AudioPlayer()
        player._volume = 0.95

        player.adjust_volume(0.1)

        assert player._volume == 1.0

    def test_adjust_volume_clamps_at_zero(self):
        player = AudioPlayer()
        player._volume = 0.05

        player.adjust_volume(-0.1)

        assert player._volume == 0.0

    def test_adjust_volume_calls_set_volume_when_initialized(self):
        player = AudioPlayer()
        player._initialized = True

        with patch("pygame.mixer.music.set_volume") as mock_sv:
            player.adjust_volume(0.1)

        mock_sv.assert_called_once_with(0.35)


class TestVolumeCommands:
    def test_volume_up_calls_adjust_volume(self):
        audio = MagicMock()
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}

        handled = apply_runtime_command(
            "VOLUME_UP",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _: None,
            audio_player=audio,
        )

        assert handled is True
        audio.adjust_volume.assert_called_once_with(0.1)

    def test_volume_down_calls_adjust_volume(self):
        audio = MagicMock()
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}

        handled = apply_runtime_command(
            "VOLUME_DOWN",
            engine=engine,
            rh_paused=rh_paused,
            step_clip=lambda _: None,
            audio_player=audio,
        )

        assert handled is True
        audio.adjust_volume.assert_called_once_with(-0.1)

    def test_volume_commands_ignored_without_audio_player(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        rh_paused = {"value": False}

        for cmd in ("VOLUME_UP", "VOLUME_DOWN"):
            handled = apply_runtime_command(
                cmd,
                engine=engine,
                rh_paused=rh_paused,
                step_clip=lambda _: None,
            )
            assert handled is False, f"{cmd} should be ignored without audio_player"


class TestVolumeVoiceCommands:
    def test_louder_maps_to_volume_up(self):
        assert VOICE_COMMANDS["louder"] == "VOLUME_UP"

    def test_quieter_maps_to_volume_down(self):
        assert VOICE_COMMANDS["quieter"] == "VOLUME_DOWN"
