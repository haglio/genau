from __future__ import annotations

import atexit
import logging
import subprocess
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np

from genau.runtime_support import hidden_subprocess_kwargs

logger = logging.getLogger(__name__)


class PlaybackClock:
    def __init__(self, *, now_source=time.monotonic) -> None:
        self._now = now_source
        self._playing = False
        self._offset_ms: float = 0.0
        self._start_time: float = 0.0

    @property
    def is_playing(self) -> bool:
        return self._playing

    @property
    def position_ms(self) -> float:
        if not self._playing:
            return self._offset_ms
        return (self._now() - self._start_time) * 1000 + self._offset_ms

    def start(self) -> None:
        self._start_time = self._now()
        self._offset_ms = 0.0
        self._playing = True

    def pause(self) -> None:
        if self._playing:
            self._offset_ms = self.position_ms
            self._playing = False

    def resume(self) -> None:
        if not self._playing:
            self._start_time = self._now()
            self._playing = True

    def seek(self, ms: float) -> None:
        self._offset_ms = ms
        if self._playing:
            self._start_time = self._now()


class VideoStream:
    def __init__(self) -> None:
        self._cap: cv2.VideoCapture | None = None
        self._fps: float = 30.0
        self._duration_ms: float = 0.0
        self._last_frame: np.ndarray | None = None
        self._last_frame_ms: float = -1.0

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def duration_ms(self) -> float:
        return self._duration_ms

    def open(self, path: Path) -> None:
        self.close()
        self._cap = cv2.VideoCapture(str(path))
        self._fps = self._cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_count = self._cap.get(cv2.CAP_PROP_FRAME_COUNT)
        self._duration_ms = (frame_count / self._fps) * 1000 if self._fps > 0 else 0
        self._last_frame = None
        self._last_frame_ms = -1.0

    def read_frame_at(self, target_ms: float) -> np.ndarray | None:
        if self._cap is None:
            return None
        frame_ms = 1000.0 / self._fps
        if self._last_frame is not None and abs(target_ms - self._last_frame_ms) < frame_ms:
            return self._last_frame
        if target_ms < self._last_frame_ms or target_ms - self._last_frame_ms > frame_ms * 10:
            self._cap.set(cv2.CAP_PROP_POS_MSEC, target_ms)
        while True:
            current = self._cap.get(cv2.CAP_PROP_POS_MSEC)
            ret, frame = self._cap.read()
            if not ret:
                return self._last_frame
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            self._last_frame = rgb
            self._last_frame_ms = current
            if current + frame_ms >= target_ms:
                return rgb

    @property
    def last_frame(self) -> np.ndarray | None:
        return self._last_frame

    @property
    def ended(self) -> bool:
        if self._cap is None:
            return True
        return self._last_frame_ms >= self._duration_ms - 100

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None


def _extract_audio(video_path: Path) -> Path | None:
    try:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        cmd = [
            "ffmpeg", "-v", "error", "-y",
            "-i", str(video_path),
            "-vn", "-acodec", "pcm_s16le",
            "-ar", "44100", "-ac", "2",
            tmp.name,
        ]
        subprocess.run(cmd, check=True, **hidden_subprocess_kwargs())
        if Path(tmp.name).stat().st_size < 1000:
            Path(tmp.name).unlink(missing_ok=True)
            return None
        atexit.register(lambda p=tmp.name: Path(p).unlink(missing_ok=True))
        return Path(tmp.name)
    except (subprocess.CalledProcessError, OSError) as exc:
        logger.debug("No audio extracted from %s: %s", video_path.name, exc)
        return None


def _extract_loop_segment(source_wav: Path, in_ms: int, out_ms: int) -> Path | None:
    try:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        in_s = in_ms / 1000
        duration_s = (out_ms - in_ms) / 1000
        cmd = [
            "ffmpeg", "-v", "error", "-y",
            "-ss", str(in_s),
            "-t", str(duration_s),
            "-i", str(source_wav),
            "-acodec", "pcm_s16le",
            tmp.name,
        ]
        subprocess.run(cmd, check=True, **hidden_subprocess_kwargs())
        atexit.register(lambda p=tmp.name: Path(p).unlink(missing_ok=True))
        return Path(tmp.name)
    except (subprocess.CalledProcessError, OSError) as exc:
        logger.debug("Failed to extract loop segment: %s", exc)
        return None


class AudioPlayer:
    def __init__(self) -> None:
        self._wav_path: Path | None = None
        self._initialized = False
        try:
            import pygame
            pygame.mixer.quit()
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=2048)
            self._initialized = True
        except Exception:
            logger.warning("Audio mixer unavailable", exc_info=True)

    def load(self, video_path: Path) -> None:
        if not self._initialized:
            return
        self.stop()
        self._wav_path = _extract_audio(video_path)

    def play(self, start_ms: float = 0) -> None:
        if not self._initialized or self._wav_path is None:
            return
        import pygame
        pygame.mixer.music.load(str(self._wav_path))
        pygame.mixer.music.play(start=start_ms / 1000)

    def pause(self) -> None:
        if not self._initialized:
            return
        import pygame
        pygame.mixer.music.pause()

    def resume(self) -> None:
        if not self._initialized:
            return
        import pygame
        pygame.mixer.music.unpause()

    def seek(self, ms: float) -> None:
        if not self._initialized or self._wav_path is None:
            return
        import pygame
        pygame.mixer.music.load(str(self._wav_path))
        pygame.mixer.music.play(start=ms / 1000)

    def start_loop(self, in_ms: int, out_ms: int) -> None:
        if not self._initialized or self._wav_path is None:
            return
        segment = _extract_loop_segment(self._wav_path, in_ms, out_ms)
        if segment is None:
            return
        import pygame
        pygame.mixer.music.load(str(segment))
        pygame.mixer.music.play(loops=-1)

    def stop_loop(self, resume_ms: float) -> None:
        self.seek(resume_ms)

    def stop(self) -> None:
        if not self._initialized:
            return
        import pygame
        pygame.mixer.music.stop()
        self._wav_path = None

    def close(self) -> None:
        self.stop()
        if self._initialized:
            import pygame
            pygame.mixer.quit()


class NullAudioPlayer:
    """Silent stand-in used when audio is muted (e.g. Fun Time integration).

    Satisfies the AudioPlayer interface as a no-op so no ffmpeg extraction
    runs and nothing is audible — Nau's video/T-Code path is unaffected.
    """

    def load(self, video_path: Path) -> None: ...
    def play(self, start_ms: float = 0) -> None: ...
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def seek(self, ms: float) -> None: ...
    def start_loop(self, in_ms: int, out_ms: int) -> None: ...
    def stop_loop(self, resume_ms: float) -> None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...


def build_audio_player(*, muted: bool) -> AudioPlayer | NullAudioPlayer:
    """Return a silent player when *muted*, otherwise the real mixer-backed one."""
    return NullAudioPlayer() if muted else AudioPlayer()
