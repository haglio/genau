from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class WaveformShape(Enum):
    SINE = "sine"
    TRIANGLE = "triangle"
    ROUNDED_SQUARE = "rounded_square"
    SAWTOOTH = "sawtooth"

MIN_BPM = 15.0
MAX_BPM = 200.0
MAX_SPEED = 100


def bpm_for_speed(speed: int) -> float:
    """Map speed 0-100 to BPM using exponential curve."""
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
        _recompute_center(self)


def toggle_playing(state: DirectControlState) -> None:
    state.playing = not state.playing


def pause_playing(state: DirectControlState) -> None:
    state.playing = False


def set_speed(state: DirectControlState, speed: int) -> None:
    speed = max(0, min(MAX_SPEED, speed))
    state.speed = speed
    state.bpm = bpm_for_speed(speed)


def adjust_speed(state: DirectControlState, delta: int) -> None:
    set_speed(state, state.speed + delta)


def _recompute_center(state: DirectControlState) -> None:
    """Set effective center from intended_center, clamped to amplitude range."""
    half = state.amplitude // 2
    state.center = max(half, min(100 - half, state.intended_center))


def set_amplitude(state: DirectControlState, value: int) -> None:
    state.amplitude = max(0, min(100, value))
    _recompute_center(state)


def adjust_amplitude(state: DirectControlState, delta: int) -> None:
    set_amplitude(state, state.amplitude + delta)


def set_center(state: DirectControlState, value: int) -> None:
    state.intended_center = max(0, min(100, value))
    _recompute_center(state)


def adjust_center(state: DirectControlState, delta: int) -> None:
    half = state.amplitude // 2
    lo, hi = half, 100 - half
    new = state.intended_center + delta
    if new < lo:
        if state.intended_center <= lo:
            return
        new = lo
    elif new > hi:
        if state.intended_center >= hi:
            return
        new = hi
    new = max(0, min(100, new))
    state.intended_center = new
    _recompute_center(state)


def cycle_shape(state: DirectControlState) -> None:
    shapes = list(WaveformShape)
    idx = shapes.index(state.shape)
    state.shape = shapes[(idx + 1) % len(shapes)]


def _waveform_raw(phase: float, shape: WaveformShape) -> float:
    """Return 0-1 normalized waveform value for one round trip per cycle."""
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
    """Convert engine phase + waveform to a display phase for frame selection.

    Maps the waveform's position (0-1 round trip) to a linear display phase so
    clip frames track the actual device position, not the raw engine phase.
    """
    raw = _waveform_raw(phase, shape)
    frac = phase % 1.0
    peak = _PEAK_PHASE[shape]
    if frac <= peak:
        return raw * 0.5
    else:
        return 1.0 - raw * 0.5


def sample_waveform(
    shape: WaveformShape,
    amplitude: int,
    center: int,
    n_points: int,
    *,
    start_phase: float = 0.0,
    phase_range: float = 1.0,
) -> list[float]:
    """Sample waveform over a phase range, returning 0-1 normalized positions."""
    return [
        phase_to_position(
            start_phase + (i / n_points) * phase_range,
            shape=shape, amplitude=amplitude, center=center,
        ) / 9999
        for i in range(n_points)
    ]


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
