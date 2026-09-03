"""Tests for GenauVR audio volume control.

The verbs that *reach* this player — VOLUME_UP, VOLUME_DOWN and the phrases
voice control says them with — are in tests/test_gvr_runtime_commands.py with
every other verb; here is only the level itself.
"""
from __future__ import annotations

from unittest.mock import patch

from genau_vr.audio import AudioPlayer


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
