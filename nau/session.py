"""Playback/loop orchestration for Nau, decoupled from pygame and the window.

Owns the playlist position, pause state, loop recording, seek/step actions,
and OSR2 output gating — everything the UI shell and the Fun Time command
channel both drive. Videos without a funscript play normally; recording and
T-Code output are simply inert for them.
"""
from __future__ import annotations

import logging
from pathlib import Path

from .funscript import load as load_funscript
from .loop_controller import LoopController, LoopState

logger = logging.getLogger(__name__)


class PlayerSession:
    def __init__(
        self,
        playlist: list[tuple[Path, Path | None]],
        *,
        video,
        audio,
        clock,
        tcode,
        start_paused: bool = False,
    ) -> None:
        if not playlist:
            raise ValueError("playlist must not be empty")
        self._playlist = list(playlist)
        self._video = video
        self._audio = audio
        self._clock = clock
        self._tcode = tcode
        self._paused = start_paused
        self._index = 0
        self._funscript = None
        self._loop_ctrl: LoopController | None = None
        self.load(0)

    @property
    def index(self) -> int:
        return self._index

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def has_funscript(self) -> bool:
        return self._funscript is not None

    @property
    def current_video(self) -> Path:
        return self._playlist[self._index][0]

    @property
    def fps(self) -> float:
        return self._video.fps

    @property
    def position_ms(self) -> float:
        return self._clock.position_ms

    @property
    def duration_ms(self) -> float:
        return self._video.duration_ms

    @property
    def loop_state(self) -> str:
        """Loop machine state as the shared vocabulary: normal/recording/looping."""
        if self._loop_ctrl is None:
            return "normal"
        return {
            LoopState.NORMAL: "normal",
            LoopState.MARKING: "recording",
            LoopState.LOOPING: "looping",
        }[self._loop_ctrl.state]

    def record_down(self) -> None:
        if self._loop_ctrl is None:
            return
        was_looping = self._loop_ctrl.state == LoopState.LOOPING
        self._loop_ctrl.on_record_down(int(self._clock.position_ms))
        if was_looping:
            self._tcode.reset()
            self._audio.stop_loop(self._clock.position_ms)

    def record_up(self) -> None:
        if self._loop_ctrl is None or self._loop_ctrl.state != LoopState.MARKING:
            return
        self._loop_ctrl.on_record_up(int(self._clock.position_ms))
        if self._loop_ctrl.state == LoopState.LOOPING:
            self._tcode.reset()
            self._clock.seek(self._loop_ctrl.in_ms)
            self._audio.start_loop(self._loop_ctrl.in_ms, self._loop_ctrl.out_ms)

    def loop_cancel(self) -> None:
        if self._loop_ctrl is None:
            return
        was_looping = self._loop_ctrl.state == LoopState.LOOPING
        self._loop_ctrl.cancel()
        if was_looping:
            self._tcode.reset()
            self._audio.stop_loop(self._clock.position_ms)

    def set_paused(self, paused: bool) -> None:
        if paused == self._paused:
            return
        self._paused = paused
        if paused:
            self._clock.pause()
            self._audio.pause()
        else:
            self._clock.resume()
            if self._audio_started:
                self._audio.resume()
            else:
                self._audio.play(self._clock.position_ms)
                self._audio_started = True

    def toggle_pause(self) -> None:
        self.set_paused(not self._paused)

    @property
    def playlist(self) -> list[tuple[Path, Path | None]]:
        return list(self._playlist)

    def step(self, delta: int) -> None:
        self.load(self._index + delta)

    def play_file(self, video_path: Path, funscript_path: Path | None) -> None:
        """Jump to *video_path*, inserting it after the current entry if new."""
        for i, (vid, _fs) in enumerate(self._playlist):
            if vid == video_path:
                self.load(i)
                return
        self._playlist.insert(self._index + 1, (video_path, funscript_path))
        self.load(self._index + 1)

    def replace_playlist(self, playlist: list[tuple[Path, Path | None]]) -> None:
        """Swap in a new playlist without interrupting the current video.

        If the current video is in the new list, the index follows it;
        otherwise the next step(+1) lands on the new list's first entry.
        """
        if not playlist:
            return
        current_entry = self._playlist[self._index]
        self._playlist = list(playlist)
        for i, (vid, _fs) in enumerate(self._playlist):
            if vid == current_entry[0]:
                self._index = i
                return
        # Current video was filtered out: keep it playing as a leading extra
        # entry so step(+1) lands on the new list's first item.
        self._playlist.insert(0, current_entry)
        self._index = 0

    def seek_by(self, delta_ms: float) -> None:
        new_pos = max(0, min(self._video.duration_ms, self._clock.position_ms + delta_ms))
        self._clock.seek(new_pos)
        self._audio.seek(new_pos)
        self._tcode.reset()

    def advance(self):
        """Per-tick update: loop wrap, OSR2 output, frame decode, auto-advance.

        Returns the frame to display (or None before the first decode).
        """
        if not self._clock.is_playing:
            return self._video.last_frame

        pos_ms = self._clock.position_ms
        if self._loop_ctrl is not None:
            loop_target = self._loop_ctrl.check_loop(pos_ms)
            if loop_target is not None:
                self._clock.seek(loop_target)
                self._tcode.reset()
                pos_ms = loop_target

        if self._funscript is not None:
            self._tcode.update(int(pos_ms), self._funscript)
        frame = self._video.read_frame_at(pos_ms)

        if self._video.ended and (
            self._loop_ctrl is None or self._loop_ctrl.state == LoopState.NORMAL
        ):
            self.load(self._index + 1)
        return frame

    def close(self) -> None:
        self._tcode.close()
        self._audio.close()
        self._video.close()

    def load(self, index: int) -> None:
        self._index = index % len(self._playlist)
        vid_path, fs_path = self._playlist[self._index]
        logger.info("Loading: %s", vid_path.name)
        self._funscript = load_funscript(fs_path) if fs_path is not None else None
        self._loop_ctrl = (
            LoopController(self._funscript) if self._funscript is not None else None
        )
        self._video.open(vid_path)
        self._audio.load(vid_path)
        self._tcode.reset()
        self._clock.seek(0)
        self._audio_started = not self._paused
        if not self._paused:
            self._clock.start()
            self._audio.play(0)
