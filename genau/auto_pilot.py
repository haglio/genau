from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .direct_control import WaveformShape, _recompute_center, set_speed

if TYPE_CHECKING:
    from .direct_control import DirectControlState


def _snap_to_5(value: float) -> int:
    return round(value / 5) * 5


@dataclass
class AutoPilotState:
    active: bool = False
    rng: random.Random = field(default_factory=random.Random)
    _last_tick: float = 0.0
    _amplitude_target: float = 100.0
    _center_target: float = 50.0
    _next_retarget: float = 0.0
    _next_speed_change: float = 0.0
    _next_shape_change: float = 0.0
    _next_clip_change: float = 0.0


def toggle_auto_pilot(state: AutoPilotState) -> None:
    state.active = not state.active


def tick_auto_pilot(
    direct: DirectControlState,
    auto: AutoPilotState,
    now: float,
    step_clip: Callable[[int], None] | None = None,
) -> None:
    if not auto.active:
        return

    dt = now - auto._last_tick
    auto._last_tick = now

    if dt <= 0 or dt > 1.0:
        return

    # Retarget amplitude and center periodically
    if now >= auto._next_retarget:
        auto._amplitude_target = auto.rng.uniform(30, 100)
        auto._center_target = auto.rng.uniform(20, 80)
        auto._next_retarget = now + auto.rng.uniform(3, 8)

    # Smooth interpolation toward targets, snapped to multiples of 5
    lerp_rate = 2.0 * dt
    direct.amplitude = _snap_to_5(max(0, min(100,
        direct.amplitude + (auto._amplitude_target - direct.amplitude) * lerp_rate
    )))
    direct.intended_center = _snap_to_5(max(0, min(100,
        direct.intended_center + (auto._center_target - direct.intended_center) * lerp_rate
    )))
    _recompute_center(direct)

    # Step speed periodically
    if now >= auto._next_speed_change:
        delta = auto.rng.choice([-5, 5])
        set_speed(direct, direct.speed + delta)
        auto._next_speed_change = now + auto.rng.uniform(2, 5)

    # Change shape periodically
    if now >= auto._next_shape_change:
        shapes = list(WaveformShape)
        direct.shape = auto.rng.choice(shapes)
        auto._next_shape_change = now + auto.rng.uniform(5, 15)

    # Advance clip periodically
    if step_clip is not None and now >= auto._next_clip_change:
        step_clip(1)
        auto._next_clip_change = now + auto.rng.uniform(8, 12)
