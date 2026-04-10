from __future__ import annotations

import socket
import time
from typing import Protocol

from .funscript import Funscript, interpolate


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


class FunscriptTCodeDriver:
    def __init__(self, sink: TCodeSink, min_interval: float = 1.0 / 30) -> None:
        self._sink = sink
        self._min_interval = min_interval
        self._last_send_time: float = -1.0

    def update(self, position_ms: int, fs: Funscript, *, now: float | None = None) -> None:
        if now is None:
            now = time.monotonic()
        if self._last_send_time >= 0 and now - self._last_send_time < self._min_interval:
            return
        pos = interpolate(fs, position_ms)
        tcode_pos = round(pos * 9999 / 100)
        interval_ms = round(self._min_interval * 1000)
        self._sink.send(format_tcode_command("L0", tcode_pos, interval_ms))
        self._last_send_time = now

    def close(self) -> None:
        self._sink.close()
