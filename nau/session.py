"""Playback/loop orchestration for Nau, decoupled from the window.

Owns the playlist position, loop recording, seek/step actions, and OSR2
output gating — everything the UI shell and the Fun Time command channel
both drive.  The actual video/audio/timeline is an mpv-backed *player*
(:class:`nau.mpv_player.MpvPlayer`): mpv hardware-decodes, keeps A/V in sync,
seeks precisely, and loops an A/B range natively, so the session just tells it
what to do and reads its clock back.  Videos without a funscript play
normally; recording and T-Code output are simply inert for them.
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
        player,
        tcode,
        start_paused: bool = False,
        version_index: dict[Path, list[tuple[Path, Path | None]]] | None = None,
    ) -> None:
        if not playlist:
            raise ValueError("playlist must not be empty")
        self._playlist = list(playlist)
        self._player = player
        self._tcode = tcode
        self._version_index = version_index or {}
        self._paused = start_paused
        self._tcode_enabled = True
        self._index = 0
        self._funscript = None
        self._loop_ctrl: LoopController | None = None
        self._last_pos_ms = 0.0
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
    def current_funscript(self):
        """The loaded Funscript, or None for unscripted videos."""
        return self._funscript

    @property
    def current_video(self) -> Path:
        return self._playlist[self._index][0]

    @property
    def position_ms(self) -> float:
        return self._player.position_ms

    @property
    def duration_ms(self) -> float:
        return self._player.duration_ms

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

    @property
    def loop_bounds(self) -> tuple[int, int] | None:
        """Active loop (in_ms, out_ms) — None unless a loop is running."""
        if self._loop_ctrl is None or self._loop_ctrl.state != LoopState.LOOPING:
            return None
        return self._loop_ctrl.in_ms, self._loop_ctrl.out_ms

    @property
    def record_in_ms(self) -> int | None:
        """In point of the loop being marked — None unless recording."""
        if self._loop_ctrl is None or self._loop_ctrl.state != LoopState.MARKING:
            return None
        return self._loop_ctrl.in_ms

    def record_down(self) -> None:
        if self._loop_ctrl is None:
            return
        was_looping = self._loop_ctrl.state == LoopState.LOOPING
        self._loop_ctrl.on_record_down(int(self._player.position_ms))
        if was_looping:
            self._exit_loop()

    def record_up(self) -> None:
        if self._loop_ctrl is None or self._loop_ctrl.state != LoopState.MARKING:
            return
        self._loop_ctrl.on_record_up(int(self._player.position_ms))
        if self._loop_ctrl.state == LoopState.LOOPING:
            # mpv loops the A/B range natively (smooth, no seek stutter).
            self._player.set_ab_loop(self._loop_ctrl.in_ms, self._loop_ctrl.out_ms)
            self._player.seek_ms(self._loop_ctrl.in_ms)
            self._tcode.reset()

    def loop_cancel(self) -> None:
        if self._loop_ctrl is None:
            return
        was_looping = self._loop_ctrl.state == LoopState.LOOPING
        self._loop_ctrl.cancel()
        if was_looping:
            self._exit_loop()

    def _exit_loop(self) -> None:
        self._player.clear_ab_loop()
        self._tcode.reset()

    def set_paused(self, paused: bool) -> None:
        if paused == self._paused:
            return
        self._paused = paused
        self._player.set_paused(paused)

    def toggle_pause(self) -> None:
        self.set_paused(not self._paused)

    def set_tcode_enabled(self, enabled: bool) -> None:
        """Gate funscript T-Code output (the SET_TCODE_ENABLED command).

        In Hybrid mode Genau drives the OSR2, so Nau must stop emitting its own
        funscript-derived T-Code or the two fight over the broker's UDP inlet.
        Muting just skips the per-tick update; re-enabling resumes from the live
        position, since the driver re-sends a waypoint on its next tick.
        """
        self._tcode_enabled = enabled

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

    def cycle_version(self) -> None:
        """Swap the current entry for its next same-content version, cyclically.

        Uses the version index (members ordered largest-first) to find the
        current video's alternates; a no-op for singletons or when no index was
        supplied.  The swap happens *in place*, so the playlist keeps one entry
        per distinct video — prev/next still navigate the deduped set rather than
        the version we cycled away from.  The new file starts from the
        beginning; nothing of the old one is preserved.
        """
        members = self._version_index.get(self.current_video)
        if members is None or len(members) <= 1:
            return
        videos = [vid for vid, _fs in members]
        try:
            pos = videos.index(self.current_video)
        except ValueError:
            return
        self._playlist[self._index] = members[(pos + 1) % len(members)]
        self.load(self._index)

    def load_playlist(self, playlist: list[tuple[Path, Path | None]]) -> None:
        """Swap in a new playlist AND jump to its first video.

        Used by the length-mode toggle, where the point is to visibly land on
        the new mode's content (shorts vs full-length) rather than keep the
        current video playing invisibly.
        """
        if not playlist:
            return
        self._playlist = list(playlist)
        self.load(0)

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
        self.seek_to(self._player.position_ms + delta_ms)

    def seek_to(self, position_ms: float) -> None:
        """Seek to an absolute position (click-to-seek / nudge)."""
        target = max(0.0, min(self._player.duration_ms, position_ms))
        self._player.seek_ms(target)
        self._tcode.reset()

    def advance(self) -> None:
        """Per-tick update: drive OSR2 output, reset on loop wrap, auto-advance.

        mpv renders the video itself, so nothing is returned — the caller reads
        the session's position/state for the overlays.
        """
        if self._paused:
            return

        pos_ms = self._player.position_ms
        # mpv's A/B loop wraps B->A by jumping the clock backwards; resend the
        # T-Code waypoint from the loop start so the OSR2 restarts cleanly.
        if (
            self._loop_ctrl is not None
            and self._loop_ctrl.state == LoopState.LOOPING
            and pos_ms + 50 < self._last_pos_ms
        ):
            self._tcode.reset()
        self._last_pos_ms = pos_ms

        if self._tcode_enabled and self._funscript is not None:
            self._tcode.update(int(pos_ms), self._funscript)

        if self._player.eof and (
            self._loop_ctrl is None or self._loop_ctrl.state == LoopState.NORMAL
        ):
            self.load(self._index + 1)

    def close(self) -> None:
        self._tcode.close()
        self._player.close()

    def load(self, index: int) -> None:
        self._index = index % len(self._playlist)
        vid_path, fs_path = self._playlist[self._index]
        logger.info("Loading: %s", vid_path.name)
        self._funscript = load_funscript(fs_path) if fs_path is not None else None
        # A loop controller exists for every video so clips can be recorded even
        # without a funscript; snapping and T-Code output stay funscript-gated.
        self._loop_ctrl = LoopController(self._funscript)
        self._player.clear_ab_loop()
        self._player.load(vid_path)
        self._player.set_paused(self._paused)
        self._tcode.reset()
        self._last_pos_ms = 0.0
