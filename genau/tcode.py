from __future__ import annotations

import time
from typing import Protocol

from .direct_control import phase_to_position


def format_tcode_command(axis: str, position: int, interval_ms: int) -> str:
    position = max(0, min(9999, position))
    interval_ms = max(0, interval_ms)
    return f"{axis}{position:04d}I{interval_ms}"


class TCodeSink(Protocol):
    def send(self, command: str) -> None: ...
    def close(self) -> None: ...


class SerialTCodeSink:
    def __init__(self, port: str = "COM4", baudrate: int = 115200) -> None:
        import serial
        self._ser = serial.Serial(port, baudrate, timeout=0)

    def send(self, command: str) -> None:
        self._ser.write((command + "\n").encode("ascii"))

    def close(self) -> None:
        self._ser.close()


class RateLimitedTCodeSender:
    def __init__(
        self,
        sink: TCodeSink,
        min_interval: float = 1.0 / 30.0,
        now_source=time.monotonic,
    ) -> None:
        self._sink = sink
        self._min_interval = min_interval
        self._now_source = now_source
        self._last_send_time: float = 0.0
        self._last_phase: float = 0.0
        self._stroke_phase: float = 0.0

    def maybe_send(self, phase: float, now: float) -> None:
        # Accumulate continuous stroke phase, detecting wraps.
        delta = phase - self._last_phase
        if delta < -0.5:
            delta += 1.0
        self._stroke_phase += max(0.0, delta)
        self._last_phase = phase

        elapsed = now - self._last_send_time
        if elapsed < self._min_interval:
            return
        interval_ms = max(1, min(9999, round(elapsed * 1000)))
        position = phase_to_position(self._stroke_phase)
        self._sink.send(format_tcode_command("L0", position, interval_ms))
        self._last_send_time = now

    def close(self) -> None:
        self._sink.close()
