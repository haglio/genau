"""Auto-advance: leaving one clip for the next on a timer, hands-free."""
from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field

# How long a clip holds the screen when nobody has named an interval.  A range
# rather than a number so the switches never settle into a countable rhythm.
DEFAULT_INTERVAL_RANGE = (8.0, 12.0)


@dataclass
class AutoAdvanceState:
    active: bool = False
    # Seconds a clip holds the screen; None means the jittered default range.
    interval: float | None = None
    # A locked clip keeps the screen while auto-advance stays armed around it.
    locked: bool = False
    rng: random.Random = field(default_factory=random.Random)
    _elapsed: float = 0.0
    _last_tick: float = 0.0
    _this_interval: float = 0.0


def toggle_auto_advance(state: AutoAdvanceState) -> None:
    if state.active:
        disable_auto_advance(state)
    else:
        enable_auto_advance(state)


def enable_auto_advance(state: AutoAdvanceState, *, interval: float | None = None) -> None:
    """Arm auto-advance, optionally naming the seconds between switches.

    A bare arming keeps whatever interval was already set, so toggling off and
    on again does not quietly forget the pace the user asked for.
    """
    state.active = True
    if interval is not None:
        state.interval = interval
        state._this_interval = interval


def disable_auto_advance(state: AutoAdvanceState) -> None:
    state.active = False
    state.locked = False


def toggle_clip_lock(state: AutoAdvanceState) -> None:
    state.locked = not state.locked


def _next_interval(state: AutoAdvanceState) -> float:
    if state.interval is not None:
        return state.interval
    return state.rng.uniform(*DEFAULT_INTERVAL_RANGE)


def tick_auto_advance(
    state: AutoAdvanceState,
    now: float,
    *,
    playing: bool,
    step_clip: Callable[[int], None],
) -> None:
    dt = now - state._last_tick
    state._last_tick = now

    # A paused room is a still one: OmniPause, and the plain space-bar pause,
    # both land here as playing=False, and neither should leave the clip the
    # user walked away from.  The elapsed count simply stops rather than
    # resetting, so resuming finishes the interval it was part-way through.
    if not state.active or state.locked or not playing:
        return

    if dt <= 0 or dt > 1.0:
        return

    if state._this_interval <= 0:
        state._this_interval = _next_interval(state)

    state._elapsed += dt
    if state._elapsed < state._this_interval:
        return

    state._elapsed = 0.0
    state._this_interval = _next_interval(state)
    step_clip(1)
