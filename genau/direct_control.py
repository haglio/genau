from __future__ import annotations

import math
from dataclasses import dataclass

MIN_BPM = 30.0
MAX_BPM = 200.0
SPEED_LEVELS = 10


def bpm_for_speed_level(level: int) -> float:
    return MIN_BPM + (level - 1) * (MAX_BPM - MIN_BPM) / (SPEED_LEVELS - 1)


@dataclass
class DirectControlState:
    playing: bool = False
    speed_level: int = 5
    bpm: float = 0.0

    def __post_init__(self) -> None:
        if self.bpm == 0.0:
            self.bpm = bpm_for_speed_level(self.speed_level)


def toggle_playing(state: DirectControlState) -> None:
    state.playing = not state.playing


def set_speed(state: DirectControlState, level: int) -> None:
    level = max(1, min(SPEED_LEVELS, level))
    state.speed_level = level
    state.bpm = bpm_for_speed_level(level)


def phase_to_position(phase: float) -> int:
    pos = 5000 + 4999 * math.sin(2 * math.pi * phase)
    return max(0, min(9999, round(pos)))
