"""Auto-advance: leaving one clip for the next on a timer, hands-free."""
from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

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
    # The clip the current interval is being measured against, and whether we
    # have already asked to move on from it.  Together these make the timer
    # count the clip that is *on screen*, not the one we requested — see
    # tick_auto_advance.
    _clip: "Path | None" = None
    _awaiting_switch: bool = False


def toggle_auto_advance(state: AutoAdvanceState) -> None:
    if state.active:
        disable_auto_advance(state)
    else:
        enable_auto_advance(state)


def enable_auto_advance(state: AutoAdvanceState, *, interval: float | None = None) -> None:
    """Arm auto-advance, optionally naming the seconds between switches.

    A bare arming keeps whatever interval was already set, so toggling off and
    on again does not quietly forget the pace the user asked for.  The count
    starts fresh on whatever clip is on screen now, rather than resuming a
    partial interval or waiting on a switch left over from a previous arming.
    """
    state.active = True
    if interval is not None:
        state.interval = interval
    state._elapsed = 0.0
    state._awaiting_switch = False
    state._clip = None


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
    on_screen_clip: "Path | None",
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

    # Measure the interval from the clip that is actually on screen, not from
    # the moment we asked to advance.  Genau can take seconds to decode a clip,
    # so a short interval timed from the request would elapse again and again
    # while the first switch was still loading — each elapse stacking another
    # decode that never got its turn on screen.  Two guards below hold the
    # count until a clip has genuinely arrived.
    if on_screen_clip is None:
        # Nothing has settled on screen yet (still decoding): don't count.
        return

    if on_screen_clip != state._clip:
        # A new clip reached the screen — start its interval from this frame.
        state._clip = on_screen_clip
        state._elapsed = 0.0
        state._this_interval = _next_interval(state)
        state._awaiting_switch = False
        return

    if state._awaiting_switch:
        # Already asked to move on; wait for that clip to arrive (the branch
        # above) before counting again, so one slow load can't stack more.
        return

    if dt <= 0 or dt > 1.0:
        return

    state._elapsed += dt
    if state._elapsed >= state._this_interval:
        state._awaiting_switch = True
        step_clip(1)
