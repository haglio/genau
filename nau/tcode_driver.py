from __future__ import annotations

import bisect
import time

from genau.tcode import TCodeSink, format_tcode_command

from .funscript import Funscript

_RESEND_INTERVAL = 0.1
# Glide to the parked position over this long, matching the broker's own park.
_PARK_INTERVAL_MS = 500
# Sentinel "segment" for the parked state, distinct from -1 ("nothing sent yet").
_PARK_SEGMENT = -2


class FunscriptTCodeDriver:
    def __init__(self, sink: TCodeSink) -> None:
        self._sink = sink
        self._last_send_time: float = -1.0
        self._last_segment: int = -1

    def update(
        self, position_ms: int, fs: Funscript, *, now: float | None = None, speed: float = 1.0
    ) -> None:
        if now is None:
            now = time.monotonic()

        park_until = fs.first_real_event_ms
        if park_until is not None and position_ms < park_until:
            # A long quiet lead-in with no real action yet: rest at the closest
            # position instead of drifting toward an action still seconds away.
            self.park(now=now)
            return

        segment = max(0, bisect.bisect_right(fs._times, position_ms) - 1)
        if self._should_send(segment, now):
            self._send_waypoint(fs, segment, position_ms, speed)
            self._mark_sent(segment, now)

    def park(self, *, now: float | None = None) -> None:
        """Rest the OSR2 at its closest position (the same place the broker parks
        it on pause), holding there.

        Drives the OSR2 when there is nothing to script from — an unscripted
        video, or a funscript's quiet lead-in.  Edge-gated like a waypoint: sent
        once on entry, then refreshed on the resend interval against packet loss.
        """
        if now is None:
            now = time.monotonic()
        if self._should_send(_PARK_SEGMENT, now):
            self._sink.send(format_tcode_command("L0", 0, _PARK_INTERVAL_MS))
            self._mark_sent(_PARK_SEGMENT, now)

    def _should_send(self, segment: int, now: float) -> bool:
        new_segment = segment != self._last_segment
        stale = (
            self._last_send_time >= 0
            and now - self._last_send_time >= _RESEND_INTERVAL
        )
        return new_segment or stale

    def _mark_sent(self, segment: int, now: float) -> None:
        self._last_segment = segment
        self._last_send_time = now

    def _send_waypoint(
        self, fs: Funscript, segment: int, position_ms: int, speed: float
    ) -> None:
        if segment + 1 < len(fs.actions):
            next_t, next_pos = fs.actions[segment + 1]
            # ``next_t - position_ms`` is the gap to the waypoint in *media* time;
            # the OSR2 executes its move in wall-clock time, so at playback rate
            # ``speed`` the move must finish in that many wall-milliseconds.
            remaining = max(1, round((next_t - position_ms) / speed))
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
