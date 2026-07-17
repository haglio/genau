"""Status file for a satellite player.

Publishes what the satellite is showing (key=value lines) so fun_time can read
its current clip, playhead and pause/lock state directly — the watch-sampler and
the lock HUD read this file instead of polling VLC's status.xml over HTTP.  Writes
are throttled, since the position changes every tick.  Deliberately shaped like
:class:`nau.status.StatusWriter`; the two are a candidate to fold into one shared
writer when the player core is extracted.
"""
from __future__ import annotations

import time
from pathlib import Path


class StatusWriter:
    def __init__(
        self,
        path: Path,
        *,
        min_interval: float = 0.2,
        now_source=time.monotonic,
    ) -> None:
        self._path = path
        self._min_interval = min_interval
        self._now = now_source
        self._last_write: float | None = None

    def write(self, session) -> bool:
        now = self._now()
        if self._last_write is not None and now - self._last_write < self._min_interval:
            return False
        text = (
            f"video={session.current_video}\n"
            f"position_ms={int(session.position_ms)}\n"
            f"duration_ms={int(session.duration_ms)}\n"
            f"paused={'1' if session.is_paused else '0'}\n"
            f"locked={'1' if session.is_locked else '0'}\n"
        )
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(text, encoding="utf-8")
        except OSError:
            return False
        self._last_write = now
        return True
