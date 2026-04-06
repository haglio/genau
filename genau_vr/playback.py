"""Playback engine, waveform generation, and T-Code output.

Copied from Genau's engine.py, direct_control.py, tcode.py, and
refresh_logic.py — flattened into a single module for GenauVR.
"""
from __future__ import annotations

import math
import socket
import time
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


# ---------------------------------------------------------------------------
# Engine (from genau/engine.py)
# ---------------------------------------------------------------------------

@dataclass
class PlaybackEngine:
    phase: float = 0.0
    estimated_bpm: float | None = None
    target_bpm: float | None = None
    last_tick: float = 0.0
    seen_sync_pulse_id: int = 0


def update_engine(
    engine: PlaybackEngine,
    *,
    now: float,
    auto_active: bool,
    raw_bpm: float | None,
    sync_pulse_id: int,
    beats_per_loop: float,
    bpm_smoothing: float,
    sync_strength: float,
    paused: bool,
) -> float | None:
    dt = now - engine.last_tick
    engine.last_tick = now
    dt = max(0.0, min(dt, 0.1))

    if raw_bpm is not None:
        engine.target_bpm = float(raw_bpm)
        if engine.estimated_bpm is None:
            engine.estimated_bpm = float(raw_bpm)

    if engine.estimated_bpm is not None and engine.target_bpm is not None:
        alpha = max(0.0, min(1.0, bpm_smoothing))
        engine.estimated_bpm = engine.estimated_bpm + (engine.target_bpm - engine.estimated_bpm) * alpha

    if auto_active and engine.estimated_bpm and engine.estimated_bpm > 0 and not paused:
        loop_duration = (60.0 / engine.estimated_bpm) * beats_per_loop
        engine.phase = (engine.phase + (dt / loop_duration)) % 1.0
    else:
        loop_duration = None

    if sync_pulse_id != engine.seen_sync_pulse_id:
        engine.seen_sync_pulse_id = sync_pulse_id
        phase = engine.phase
        error = -phase if phase <= 0.5 else (1.0 - phase)
        strength = max(0.0, min(1.0, sync_strength))
        engine.phase = (engine.phase + error * strength) % 1.0

    return loop_duration


# ---------------------------------------------------------------------------
# Waveform / Direct control (from genau/direct_control.py)
# ---------------------------------------------------------------------------

class WaveformShape(Enum):
    SINE = "sine"
    TRIANGLE = "triangle"
    ROUNDED_SQUARE = "rounded_square"
    SAWTOOTH = "sawtooth"


MIN_BPM = 15.0
MAX_BPM = 200.0
MAX_SPEED = 100


def bpm_for_speed(speed: int) -> float:
    return MIN_BPM * (MAX_BPM / MIN_BPM) ** (speed / MAX_SPEED)


@dataclass
class DirectControlState:
    playing: bool = False
    speed: int = 50
    bpm: float = 0.0
    amplitude: int = 100
    center: int = 50
    intended_center: int = 50
    shape: WaveformShape = WaveformShape.SINE

    def __post_init__(self) -> None:
        if self.bpm == 0.0:
            self.bpm = bpm_for_speed(self.speed)
        half = self.amplitude // 2
        self.center = max(half, min(100 - half, self.intended_center))


def _waveform_raw(phase: float, shape: WaveformShape) -> float:
    frac = phase % 1.0
    if shape is WaveformShape.SINE:
        return (1 - math.cos(2 * math.pi * phase)) / 2
    elif shape is WaveformShape.TRIANGLE:
        return 1 - abs(2 * frac - 1)
    elif shape is WaveformShape.ROUNDED_SQUARE:
        k = 3.0
        return (1 - math.tanh(k * math.cos(2 * math.pi * frac)) / math.tanh(k)) / 2
    elif shape is WaveformShape.SAWTOOTH:
        rise = 0.3
        if frac < rise:
            return frac / rise
        else:
            return 1 - (frac - rise) / (1 - rise)
    return (1 - math.cos(2 * math.pi * phase)) / 2


_PEAK_PHASE = {
    WaveformShape.SINE: 0.5,
    WaveformShape.TRIANGLE: 0.5,
    WaveformShape.ROUNDED_SQUARE: 0.5,
    WaveformShape.SAWTOOTH: 0.3,
}


def display_phase_for_position(phase: float, shape: WaveformShape) -> float:
    raw = _waveform_raw(phase, shape)
    frac = phase % 1.0
    peak = _PEAK_PHASE[shape]
    if frac <= peak:
        return raw * 0.5
    else:
        return 1.0 - raw * 0.5


def phase_to_position(
    phase: float,
    *,
    shape: WaveformShape = WaveformShape.SINE,
    amplitude: int = 100,
    center: int = 50,
) -> int:
    raw = _waveform_raw(phase, shape)
    center_pos = center / 100 * 9999
    half_range = amplitude / 100 * 9999 / 2
    low = max(0, center_pos - half_range)
    high = min(9999, center_pos + half_range)
    return max(0, min(9999, round(low + raw * (high - low))))


# ---------------------------------------------------------------------------
# T-Code (from genau/tcode.py)
# ---------------------------------------------------------------------------

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

    def maybe_send(self, phase: float, now: float) -> None:
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


# ---------------------------------------------------------------------------
# Frame index selection (from genau/refresh_logic.py)
# ---------------------------------------------------------------------------

def display_index_for_phase(
    *,
    phase: float,
    frame_count: int,
    auto_active: bool,
    current_frame_index: int | None,
) -> int:
    logical_index = int(phase * frame_count)
    if logical_index >= frame_count:
        logical_index = frame_count - 1

    display_index = (frame_count - 1) - logical_index
    if not auto_active and current_frame_index is not None:
        return current_frame_index
    return display_index
