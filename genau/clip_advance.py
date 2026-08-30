"""How long a clip holds the screen, and the lock that stops it moving at all.

Genau's clips are fractions of a second long, so playing them the way a playlist
plays videos would be a strobe: every clip has to repeat for a while before the
next one arrives.  That "while" is the interval here.  The lock is the same lock
every player in this family has — repeat-one on what is on screen — and it is on
by default, because a held clip is what Genau has always opened on.

There is no separate "auto advance" switch any more: advancing is simply what an
unlocked Genau does, and the interval is how fast.  The pair used to be two
controls that could disagree (armed but held, held but disarmed), and on the
main console they sat next to the lock of the player sharing the slot.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

# Seconds a clip holds the screen, and the range the controls move it through.
# One second is already a strobe; a minute is longer than anyone waits for a
# switch they asked to be automatic.
DEFAULT_INTERVAL_S = 10
MIN_INTERVAL_S = 1
MAX_INTERVAL_S = 60


@dataclass
class ClipAdvanceState:
    # Locked, the clip on screen repeats and nothing moves it but a press.
    locked: bool = True
    # Seconds each clip holds the screen while unlocked.
    interval: int = DEFAULT_INTERVAL_S
    _elapsed: float = 0.0
    _last_tick: float = 0.0
    # The clip the current interval is being measured against, and whether we
    # have already asked to move on from it.  Together these make the timer
    # count the clip that is *on screen*, not the one we requested — see
    # tick_clip_advance.
    _clip: "Path | None" = None
    _awaiting_switch: bool = False


def set_locked(state: ClipAdvanceState, locked: bool) -> None:
    """Hold the clip on screen, or let the interval carry it on.

    Unlocking starts the count fresh on whatever is on screen now, rather than
    resuming a part-finished interval or acting on a switch left over from
    before the lock — so the first clip after an unlock gets a full turn.
    """
    state.locked = locked
    if not locked:
        state._elapsed = 0.0
        state._awaiting_switch = False
        state._clip = None


def toggle_lock(state: ClipAdvanceState) -> None:
    set_locked(state, not state.locked)


def set_interval(state: ClipAdvanceState, seconds: int) -> None:
    """Set the seconds a clip holds the screen, clamped to the usable range."""
    state.interval = max(MIN_INTERVAL_S, min(MAX_INTERVAL_S, int(seconds)))


def adjust_interval(state: ClipAdvanceState, delta: int) -> None:
    set_interval(state, state.interval + delta)


def tick_clip_advance(
    state: ClipAdvanceState,
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
    if state.locked or not playing:
        return

    # Measure the interval from the clip that is actually on screen, not from
    # the moment we asked to advance.  Genau can take seconds to decode a clip,
    # so a short interval timed from the request would elapse again and again
    # while the first switch was still loading — each elapse stacking another
    # decode that never got its turn on screen.  Two guards below hold the
    # count until a clip has genuinely arrived.
    if on_screen_clip is None:
        return

    if on_screen_clip != state._clip:
        state._clip = on_screen_clip
        state._elapsed = 0.0
        state._awaiting_switch = False
        return

    if state._awaiting_switch:
        return

    if dt <= 0 or dt > 1.0:
        return

    state._elapsed += dt
    if state._elapsed >= state.interval:
        state._awaiting_switch = True
        step_clip(1)
