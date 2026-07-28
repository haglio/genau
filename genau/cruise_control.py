from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .direct_control import WaveformShape, _recompute_center, set_speed

if TYPE_CHECKING:
    from .direct_control import DirectControlState


def _snap_to_5(value: float) -> int:
    return round(value / 5) * 5


@dataclass
class CruiseControlState:
    """Hands-free variation of the stroke itself — never of which clip plays.

    Moving on to another clip is :mod:`genau.clip_advance`'s job, and the two are
    independent: a session can vary the stroke on one held clip, or hold the
    stroke steady while the clips change, or both.
    """

    active: bool = False
    rng: random.Random = field(default_factory=random.Random)
    _last_tick: float = 0.0
    _amplitude_target: float = 100.0
    _center_target: float = 50.0
    _next_retarget: float = 0.0
    _next_speed_change: float = 0.0
    _next_shape_change: float = 0.0


def toggle_cruise_control(state: CruiseControlState) -> None:
    state.active = not state.active


def enable_cruise_control(state: CruiseControlState) -> None:
    state.active = True


def disable_cruise_control(state: CruiseControlState) -> None:
    state.active = False


def tick_cruise_control(
    direct: DirectControlState,
    cc: CruiseControlState,
    now: float,
) -> None:
    if not cc.active:
        return

    # Armed but not stroking — paused by hand, or frozen under OmniPause, or (in
    # Hybrid) sitting out while a funscript has the device.  Auto advance has
    # always sat still then; cruise went on quietly moving amplitude, centre,
    # speed and shape, so a session came back from a pause to a stroke it never
    # asked for.  The clock keeps up so resuming picks up where it left off.
    if not direct.playing:
        cc._last_tick = now
        return

    dt = now - cc._last_tick
    cc._last_tick = now

    if dt <= 0 or dt > 1.0:
        return

    # Retarget amplitude and center periodically
    if now >= cc._next_retarget:
        cc._amplitude_target = cc.rng.uniform(30, 100)
        cc._center_target = cc.rng.uniform(20, 80)
        cc._next_retarget = now + cc.rng.uniform(3, 8)

    # Smooth interpolation toward targets, snapped to multiples of 5
    lerp_rate = 2.0 * dt
    direct.amplitude = _snap_to_5(max(0, min(100,
        direct.amplitude + (cc._amplitude_target - direct.amplitude) * lerp_rate
    )))
    direct.intended_center = _snap_to_5(max(0, min(100,
        direct.intended_center + (cc._center_target - direct.intended_center) * lerp_rate
    )))
    _recompute_center(direct)

    # Step speed periodically
    if now >= cc._next_speed_change:
        delta = cc.rng.choice([-5, 5])
        set_speed(direct, direct.speed + delta)
        cc._next_speed_change = now + cc.rng.uniform(2, 5)

    # Change shape periodically
    if now >= cc._next_shape_change:
        shapes = list(WaveformShape)
        direct.shape = cc.rng.choice(shapes)
        cc._next_shape_change = now + cc.rng.uniform(5, 15)
