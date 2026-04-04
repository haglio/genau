from __future__ import annotations

import socket
import time
from typing import TYPE_CHECKING, Protocol

from .direct_control import phase_to_position

if TYPE_CHECKING:
    from .direct_control import DirectControlState


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


class RateLimitedTCodeSender:
    def __init__(
        self,
        sink: TCodeSink,
        *,
        direct_state: DirectControlState | None = None,
        min_interval: float = 1.0 / 30.0,
        now_source=time.monotonic,
    ) -> None:
        self._sink = sink
        self._direct_state = direct_state
        self._min_interval = min_interval
        self._now_source = now_source
        self._last_send_time: float = 0.0
        self._last_phase: float = 0.0
        self._stroke_phase: float = 0.0

    def _compute_position(self) -> int:
        if self._direct_state is not None:
            return phase_to_position(
                self._stroke_phase,
                shape=self._direct_state.shape,
                amplitude=self._direct_state.amplitude,
                center=self._direct_state.center,
            )
        return phase_to_position(self._stroke_phase)

    def current_position(self) -> int:
        return self._compute_position()

    @property
    def stroke_phase(self) -> float:
        return self._stroke_phase

    @property
    def stroke_phase_frac(self) -> float:
        return self._stroke_phase % 1.0

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
        position = self._compute_position()
        self._sink.send(format_tcode_command("L0", position, interval_ms))
        self._last_send_time = now

    def close(self) -> None:
        self._sink.close()
