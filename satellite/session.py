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

    @property
    def playlist(self) -> list[Path]:
        """A copy of the current playlist, so callers cannot mutate it in place."""
        return list(self._playlist)

    @property
    def position_ms(self) -> float:
        return self._player.position_ms

    @property
    def duration_ms(self) -> float:
        return self._player.duration_ms

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

    def discard(self) -> None:
        """Drop the current clip from the playlist and play the next one — the
        satellite's "trash" gesture.

        The next clip shifts into the current index, so re-loading that index
        lands on it; discarding the last entry wraps to the first.  A satellite
        must always have something to play, so the final remaining clip cannot be
        discarded — that is a no-op, never an empty playlist.
        """
        if len(self._playlist) <= 1:
            return
        del self._playlist[self._index]
        self.load(self._index)

    def play_file(self, video: Path) -> None:
        """Jump to *video* if it is already in the playlist, else splice it in
        after the current clip and play it.

        Powers "play this exact clip": a lock's back-dating (bring back the clip
        the speaker actually saw) and a HUD switch both target a member, so those
        just jump; a newcomer from outside the list is inserted next and played.
        """
        for i, path in enumerate(self._playlist):
            if path == video:
                self.load(i)
                return
        self._playlist.insert(self._index + 1, video)
        self.load(self._index + 1)

    def load_playlist(self, playlist: list[Path]) -> None:
        """Swap in a whole new playlist and restart at the top.

        A fresh browse — a filter or a group loop — that should begin from the
        start of the new set.
        """
        if not playlist:
            raise ValueError("playlist must not be empty")
        self._playlist = list(playlist)
        self.load(0)

    def replace_playlist(self, playlist: list[Path]) -> None:
        """Swap in a rebuilt playlist but keep playing the current clip if it
        survives, else restart at the top.

        A reload where continuity matters — an F-mode toggle rebuilds the list,
        and the clip on screen should keep playing uninterrupted when it is still
        present rather than flicker back to a reload.
        """
        if not playlist:
            raise ValueError("playlist must not be empty")
        current = self.current_video
        self._playlist = list(playlist)
        for i, path in enumerate(self._playlist):
            if path == current:
                self._index = i
                return
        self.load(0)

    def load(self, index: int) -> None:
        self._index = index % len(self._playlist)
        video = self._playlist[self._index]
        logger.info("Loading: %s", video.name)
        self._player.load(video)
        self._player.set_paused(self._paused)

    def close(self) -> None:
        """Tear down the underlying player (mpv terminate) on shutdown."""
        self._player.close()
