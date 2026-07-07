"""Status file for the Fun Time orchestrator.

Publishes what Nau is playing and doing (key=value lines) so the dispatch
side can drive clipper_save, the dashboard funscript highlight, and the
record-button state. Writes are throttled — position changes every tick.
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
            f"has_funscript={'1' if session.has_funscript else '0'}\n"
            f"funscript_resting={'1' if session.funscript_resting else '0'}\n"
            f"state={session.loop_state}\n"
            f"paused={'1' if session.is_paused else '0'}\n"
        )
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(text, encoding="utf-8")
        except OSError:
            return False
        self._last_write = now
        return True
