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
SPEED_LEVELS = 10


def bpm_for_speed_level(level: int) -> float:
    return MIN_BPM * (MAX_BPM / MIN_BPM) ** ((level - 1) / (SPEED_LEVELS - 1))


@dataclass
class DirectControlState:
    playing: bool = False
    speed_level: int = 5
    bpm: float = 0.0
    amplitude: int = 100
    center: int = 50
    shape: WaveformShape = WaveformShape.SINE

    def __post_init__(self) -> None:
        if self.bpm == 0.0:
            self.bpm = bpm_for_speed_level(self.speed_level)


def toggle_playing(state: DirectControlState) -> None:
    state.playing = not state.playing


def set_speed(state: DirectControlState, level: int) -> None:
    level = max(1, min(SPEED_LEVELS, level))
    state.speed_level = level
    state.bpm = bpm_for_speed_level(level)


def adjust_speed(state: DirectControlState, delta: int) -> None:
    set_speed(state, state.speed_level + delta)


def adjust_amplitude(state: DirectControlState, delta: int) -> None:
    state.amplitude = max(0, min(100, state.amplitude + delta))


def adjust_center(state: DirectControlState, delta: int) -> None:
    state.center = max(0, min(100, state.center + delta))


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


def sample_waveform(
    shape: WaveformShape,
    amplitude: int,
    center: int,
    n_points: int,
) -> list[float]:
    """Sample one cycle of the waveform, returning 0-1 normalized positions."""
    return [
        phase_to_position(i / n_points, shape=shape, amplitude=amplitude, center=center) / 9999
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
