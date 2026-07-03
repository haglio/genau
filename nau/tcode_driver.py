from __future__ import annotations

import bisect
import time

from genau.tcode import TCodeSink, format_tcode_command

from .funscript import Funscript

_RESEND_INTERVAL = 0.1


class FunscriptTCodeDriver:
    def __init__(self, sink: TCodeSink, min_interval: float = 1.0 / 30) -> None:
        self._sink = sink
        self._min_interval = min_interval
        self._last_send_time: float = -1.0
        self._last_segment: int = -1

    def update(self, position_ms: int, fs: Funscript, *, now: float | None = None) -> None:
        if now is None:
            now = time.monotonic()
        segment = bisect.bisect_right(fs._times, position_ms) - 1
        segment = max(0, segment)

        new_segment = segment != self._last_segment
        stale = (
            self._last_send_time >= 0
            and now - self._last_send_time >= _RESEND_INTERVAL
        )
        if not new_segment and not stale:
            return

        self._last_segment = segment
        self._send_waypoint(fs, segment, position_ms)
        self._last_send_time = now

    def _send_waypoint(self, fs: Funscript, segment: int, position_ms: int) -> None:
        if segment + 1 < len(fs.actions):
            next_t, next_pos = fs.actions[segment + 1]
            remaining = max(1, next_t - position_ms)
            tcode_pos = round(next_pos * 9999 / 100)
            self._sink.send(format_tcode_command("L0", tcode_pos, remaining))
        else:
            _, pos = fs.actions[-1]
            tcode_pos = round(pos * 9999 / 100)
            self._sink.send(format_tcode_command("L0", tcode_pos, 100))

    def reset(self) -> None:
        self._last_segment = -1
        self._last_send_time = -1.0

    def close(self) -> None:
        self._sink.close()
