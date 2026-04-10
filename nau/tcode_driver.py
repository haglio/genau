from __future__ import annotations

import bisect
import socket
import time
from typing import Protocol

from .funscript import Funscript


def format_tcode_command(axis: str, position: int, interval_ms: int) -> str:
    position = max(0, min(9999, position))
    interval_ms = max(0, interval_ms)
    return f"{axis}{position:04d}I{interval_ms}"


class TCodeSink(Protocol):
    def send(self, command: str) -> None: ...
    def close(self) -> None: ...


class UdpTCodeSink:
    def __init__(self, host: str = "127.0.0.1", port: int = 50557, *, sock=None) -> None:
        self._host = host
        self._port = port
        self._sock = sock if sock is not None else socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, command: str) -> None:
        self._sock.sendto((command + "\n").encode("ascii"), (self._host, self._port))

    def close(self) -> None:
        self._sock.close()


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
