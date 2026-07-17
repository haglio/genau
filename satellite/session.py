"""Playlist/navigation orchestration for a satellite player, decoupled from the
window.

A satellite is the simple half of Nau: an unscripted, silent looper of short
clips.  It owns its playlist position and drives an mpv-backed *player*
(:class:`nau.mpv_player.MpvPlayer`) to load/pause/seek — but there is no
funscript, no OSR2/T-Code, no loop recording and no audio, so this session is a
fraction of :class:`nau.session.PlayerSession`.  Navigation is fully in-process
(a Python list + index), which is the whole point of leaving VLC behind: no HTTP
playlist to resolve ids against, and pausing is a flag the player obeys.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class SatelliteSession:
    def __init__(
        self,
        playlist: list[Path],
        *,
        player,
        start_paused: bool = False,
    ) -> None:
        if not playlist:
            raise ValueError("playlist must not be empty")
        self._playlist = list(playlist)
        self._player = player
        self._paused = start_paused
        self._locked = False
        self._index = 0
        self.load(0)

    @property
    def index(self) -> int:
        return self._index

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def is_locked(self) -> bool:
        return self._locked

    @property
    def current_video(self) -> Path:
        return self._playlist[self._index]

    def step(self, delta: int) -> None:
        """Navigate *delta* items (next = +1, prev = -1), wrapping the playlist."""
        self.load(self._index + delta)

    def set_paused(self, paused: bool) -> None:
        if paused == self._paused:
            return
        self._paused = paused
        self._player.set_paused(paused)

    def toggle_pause(self) -> None:
        self.set_paused(not self._paused)

    def set_locked(self, locked: bool) -> None:
        """Lock the satellite onto its current clip (repeat-one) or release it.

        Locking hands the repeat to mpv's own ``loop_file`` so a short clip
        loops seamlessly in place; :meth:`advance` then never walks off it.
        Unlocking restores playlist auto-advance at end-of-file.
        """
        self._locked = locked
        self._player.set_loop_file(locked)

    def advance(self) -> None:
        """Per-tick update: auto-advance to the next clip when the current one
        ends.

        mpv renders the video itself, so nothing is returned — the caller reads
        the session's position/state for the overlays.  A paused satellite never
        advances, which is what makes OmniPause a settled state: freeze the flag
        and the playlist cannot walk on its own (the whole reason VLC needed a
        re-pause watchdog).  A locked satellite holds its clip too (repeat-one).
        """
        if self._paused or self._locked:
            return
        if self._player.eof:
            self.load(self._index + 1)

    def load(self, index: int) -> None:
        self._index = index % len(self._playlist)
        video = self._playlist[self._index]
        logger.info("Loading: %s", video.name)
        self._player.load(video)
        self._player.set_paused(self._paused)
