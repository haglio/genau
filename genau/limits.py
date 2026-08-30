"""Which of the hand's arrows would do nothing.

Six booleans, published twice: the status file Fun Time reads has them so its
dashboard can dim a button, and the drive readout Nau draws has them so the
console can dim an arrow.  They are two publications of one fact, and they used
to be worked out separately, including the centre clamp -- so a change to the
clamp had to be made in both places or the console dimmed an arrow the status
file called live.
"""
from __future__ import annotations

from dataclasses import dataclass

from player_core.direct_control import MAX_SPEED, MIN_SPEED, DirectControlState


@dataclass(frozen=True)
class ControlLimits:
    amp_at_max: bool
    amp_at_min: bool
    ctr_at_max: bool
    ctr_at_min: bool
    spd_at_max: bool
    spd_at_min: bool


def control_limits(direct: DirectControlState) -> ControlLimits:
    # The centre's range is what the travel leaves it: it cannot push a stroke
    # off the top or bottom of the device, so it stops half a travel in from
    # each end.
    half = direct.amplitude // 2
    return ControlLimits(
        amp_at_max=direct.amplitude >= 100,
        amp_at_min=direct.amplitude <= 0,
        ctr_at_max=direct.center >= 100 - half,
        ctr_at_min=direct.center <= half,
        spd_at_max=direct.speed >= MAX_SPEED,
        spd_at_min=direct.speed <= MIN_SPEED,
    )
