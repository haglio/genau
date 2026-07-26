"""Playback/loop orchestration for Nau, decoupled from the window.

Owns the playlist position, loop recording, seek/step actions, and OSR2
output gating — everything the UI shell and the Fun Time command channel
both drive.  The actual video/audio/timeline is an mpv-backed *player*
(:class:`player_core.mpv_player.MpvPlayer`): mpv hardware-decodes, keeps A/V in sync,
seeks precisely, and loops an A/B range natively, so the session just tells it
what to do and reads its clock back.  Videos without a funscript play
normally: the OSR2 rests at its parked position with no script to follow, and
loop recording falls back to raw clip ranges without funscript snapping.
"""
from __future__ import annotations

import logging
from pathlib import Path

from player_core.funscript import load as load_funscript
from .loop_controller import LoopController, LoopState

logger = logging.getLogger(__name__)

# A backward jump larger than this (ms) means the playback clock rewound rather
# than merely ticking forward.  A rewind that also lands within
# _EOF_WRAP_START_MS of zero is the file wrapping at EOF (mpv loop-file=inf
# restarts at 0), as opposed to a user seeking backward to some interior point.
_REWIND_MS = 50
_EOF_WRAP_START_MS = 250

# While marking a loop, close it once the playhead comes within this of the
# file end — proactively, so mpv's A/B loop takes over before loop-file wraps
# the whole video to the start and flashes the opening frames.  Wide enough that
# a tick reliably lands inside it at 60 fps, small enough to still feel instant.
_EOF_MARGIN_MS = 100

# Playback-rate bounds for the speed control (mpv's ``speed`` multiplier, where
# 1.0 is normal). The funscript follows a speed change automatically because it
# is driven off mpv's clock, which advances at the playback rate.
MIN_SPEED_RATE = 0.25
MAX_SPEED_RATE = 2.0

# Volume bounds for the audio control, on mpv's ``volume`` scale: a percentage
# of the source's own level, where 100 is untouched and 0 is silent.
MIN_VOLUME = 0
MAX_VOLUME = 100


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
        self._speed = 1.0
        self._volume = MAX_VOLUME
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
    def funscript_resting(self) -> bool:
        """Whether the current spot sits in the funscript's quiet lead-in or an
        interior gap (a buffer past the nearest dense action), where the script
        has nothing to say.  Hybrid hands these stretches to Genau.  False when
        there is no funscript — there is then nothing to rest between.
        """
        if self._funscript is None:
            return False
        return self._funscript.is_resting_at(int(self.position_ms))

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
        self._finalize_loop(int(self._player.position_ms))

    def _finalize_loop(self, out_ms: int) -> None:
        """Close the marked loop at *out_ms* and start mpv's native A/B loop."""
        self._loop_ctrl.on_record_up(out_ms)
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

    @property
    def speed(self) -> float:
        """Playback rate multiplier (1.0 = normal)."""
        return self._speed

    def set_speed(self, speed: float) -> None:
        """Change the playback rate, clamped to the supported range.

        mpv retimes the video and its clock, so the funscript stays in sync on
        its own; the T-Code driver is reset to re-time the in-flight move at the
        new rate rather than wait out the current (now mistimed) one.
        """
        speed = max(MIN_SPEED_RATE, min(MAX_SPEED_RATE, speed))
        if speed == self._speed:
            return
        self._speed = speed
        self._player.set_speed(speed)
        self._tcode.reset()

    def adjust_speed(self, delta: float) -> None:
        self.set_speed(self._speed + delta)

    @property
    def volume(self) -> int:
        """Playback volume: a percentage of the source's own level."""
        return self._volume

    def set_volume(self, volume: int) -> None:
        self._volume = max(MIN_VOLUME, min(MAX_VOLUME, volume))
        self._player.set_volume(self._volume)

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
        """Swap in a new playlist, keeping the current video only if it survives.

        If the current video is still in the new list, playback continues on it
        uninterrupted (the index just follows it).  Otherwise it was filtered
        out — e.g. an unscripted video when F-mode reloads the funscript-only
        list — so jump straight to the new list's first entry rather than
        stranding it on screen, mirroring how the satellites restart at item 0.
        """
        if not playlist:
            return
        current_entry = self._playlist[self._index]
        self._playlist = list(playlist)
        for i, (vid, _fs) in enumerate(self._playlist):
            if vid == current_entry[0]:
                self._index = i
                return
        # Current video was filtered out — jump to the new list's first entry.
        self.load(0)

    def seek_by(self, delta_ms: float) -> None:
        self.seek_to(self._player.position_ms + delta_ms)

    def seek_to(self, position_ms: float) -> None:
        """Seek to an absolute position (click-to-seek / nudge).

        While marking a loop, the record-down point is a floor: a backward seek
        can't rewind before where the loop started — it lands on the start.
        """
        floor = 0.0 if self.record_in_ms is None else float(self.record_in_ms)
        target = max(floor, min(self._player.duration_ms, position_ms))
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
        rewound = pos_ms + _REWIND_MS < self._last_pos_ms
        prev_pos_ms = self._last_pos_ms
        self._last_pos_ms = pos_ms

        if self._loop_ctrl is not None:
            if self._loop_ctrl.state == LoopState.MARKING:
                duration_ms = self._player.duration_ms
                near_end = (
                    duration_ms > 0 and pos_ms >= duration_ms - _EOF_MARGIN_MS
                )
                wrapped = rewound and pos_ms < _EOF_WRAP_START_MS
                if near_end or wrapped:
                    # Recording ran to the end of the file: close the loop at the
                    # end and start it now.  near_end fires just before loop-file
                    # (inf) wraps the whole video to the start, so the A/B loop
                    # takes over without the opening frames flashing; wrapped is
                    # the fallback if a tick only lands after the wrap.  Either
                    # way the out point stays just short of the file end, which
                    # mpv loops cleanly.
                    self._finalize_loop(int(pos_ms if near_end else prev_pos_ms))
                    return
            elif self._loop_ctrl.state == LoopState.LOOPING and rewound:
                # mpv's A/B loop wraps B->A by rewinding the clock; resend the
                # T-Code waypoint from the loop start so the OSR2 restarts cleanly.
                self._tcode.reset()

        if self._tcode_enabled:
            if self._funscript is not None:
                self._tcode.update(int(pos_ms), self._funscript, speed=self._speed)
            else:
                # No funscript to drive from: rest the OSR2 at its closest
                # position rather than leave it wherever the last video left it.
                self._tcode.park()

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
        # without a funscript; only its snapping is funscript-gated (raw ranges
        # otherwise).
        self._loop_ctrl = LoopController(self._funscript)
        self._player.clear_ab_loop()
        self._player.load(vid_path)
        self._player.set_paused(self._paused)
        self._tcode.reset()
        self._last_pos_ms = 0.0
