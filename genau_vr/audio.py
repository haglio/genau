"""The clip's own sound: a loop beside the picture, not synced to its phase.

The mixer is opened once at startup and the player degrades to silence if it
cannot be -- a headset without a working audio device should still show the clip.
Every pygame import below is deferred for the same reason: a build with no mixer
never reaches them.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Which audio device to prefer when the headset's own is present.  Matched by
# substring on the device name, case-insensitively.
_PREFERRED_DEVICE_MATCH = "pimax"

# Where a clip's sound lives: an ``audio/`` folder beside the clips folder,
# holding an MP3 named for the clip.
_AUDIO_FOLDER = "audio"
_AUDIO_SUFFIX = ".mp3"

# The level a session opens at, quiet enough not to startle.
DEFAULT_VOLUME = 0.25


class AudioPlayer:
    """Manages looping audio playback. Audio plays continuously, not synced to phase."""

    def __init__(self) -> None:
        self._initialized = False
        self._volume = DEFAULT_VOLUME
        try:
            import pygame
            pygame.init()
            from pygame._sdl2.audio import get_audio_device_names
            device = None
            for name in get_audio_device_names(False):
                if _PREFERRED_DEVICE_MATCH in name.lower():
                    device = name
                    break
            pygame.mixer.quit()
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=2048,
                              devicename=device)
            self._initialized = True
            logger.info("Audio mixer initialized (device=%s)", device or "default")
        except Exception:
            logger.warning("Audio mixer unavailable", exc_info=True)

    def load_for_clip(self, clip_path: Path) -> None:
        if not self._initialized:
            return
        import pygame
        self.stop()
        audio_path = self._find_audio(clip_path)
        if audio_path is None:
            logger.info("No audio found for clip: %s", clip_path.name)
            return
        try:
            pygame.mixer.music.load(str(audio_path))
            pygame.mixer.music.play(loops=-1)
            pygame.mixer.music.set_volume(self._volume)
            logger.info("Audio playing: %s", audio_path.name)
        except Exception:
            logger.warning("Failed to load audio", exc_info=True)

    @staticmethod
    def _find_audio(clip_path: Path) -> Path | None:
        """The MP3 named for this clip in the audio/ folder beside the clips."""
        audio_dir = clip_path.parent.parent / _AUDIO_FOLDER
        mp3 = audio_dir / (clip_path.stem + _AUDIO_SUFFIX)
        if mp3.exists():
            return mp3
        return None

    def adjust_volume(self, delta: float) -> None:
        self._volume = max(0.0, min(1.0, self._volume + delta))
        if not self._initialized:
            return
        import pygame
        pygame.mixer.music.set_volume(self._volume)

    def stop(self) -> None:
        if not self._initialized:
            return
        import pygame
        pygame.mixer.music.stop()

    def close(self) -> None:
        self.stop()
        if self._initialized:
            import pygame
            pygame.mixer.quit()
