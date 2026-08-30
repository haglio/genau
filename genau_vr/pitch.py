"""Tilting the picture with the thumbstick.

A VR180 clip is shot at whatever height its camera was at, and the viewer is
lying down as often as sitting up; the thumbstick tilts the whole projection to
meet them.  It is the one control that moves continuously rather than in steps,
which is why it is a rate rather than an amount: how fast the picture turns
while the stick is held, not how far one push moves it.
"""
from __future__ import annotations

import math

import numpy as np

from .projection import pitch_rotation_matrix

# How far off center the stick has to be before it counts.  A resting stick
# reports small non-zero values, and without this the picture drifts on its own.
THUMBSTICK_DEADZONE = 0.1

# How fast the picture turns while the stick is held all the way over --
# 1.5 rad/s, about 85 degrees a second.
PITCH_RATE_RAD_PER_S = 1.5

# Straight up and straight down: past either the picture would be upside down.
PITCH_LIMIT_RAD = math.pi / 2


class PitchControl:
    def __init__(self, offset: float = 0.0) -> None:
        self.offset = offset

    def follow(self, thumbstick_y: float, dt: float) -> None:
        """Turn the picture for as long as the stick is held.

        Pushing forward tilts the picture down, which is what makes the world
        appear to rotate the way the stick is pushed rather than against it.
        """
        if abs(thumbstick_y) <= THUMBSTICK_DEADZONE:
            return
        moved = self.offset - thumbstick_y * dt * PITCH_RATE_RAD_PER_S
        self.offset = max(-PITCH_LIMIT_RAD, min(PITCH_LIMIT_RAD, moved))

    def matrix(self) -> np.ndarray | None:
        """The rotation to fold into the view, or None when there is none.

        None rather than an identity matrix, so an untilted frame skips a
        matrix multiply per eye per frame.
        """
        if self.offset == 0.0:
            return None
        return pitch_rotation_matrix(self.offset)
