"""Where a trace holds the descents it has already chosen.

:mod:`nau.drive_trace` chooses, once per approaching turn, how the blue leaves
the device there: the top the grey ramps down from, and the touch-down it runs
to instead when there is one.  Chosen once and then HELD -- re-read live every
frame the answer breathes with the beat between Genau's publish cadence and the
frame clock, and the seam flickers.

Three modules meet around what is held.  The trace writes it as it paints,
:mod:`nau.status` reads the chosen touch out of it to publish for the arbiter,
and :mod:`nau.drive_gate` voids the lot when the wave stops describing this
approach.  They shared a bare dict of anonymous 3-tuples for that, indexed by
position at every one of those sites, one of them into a tuple inside a tuple;
the name of each slot lived only in a comment.  The type is here instead, so
the three say what they mean and there is one place a fourth would come to.

Holding also means letting go: a session runs for hours and every turn it
approaches leaves an entry behind it, so the ones the playhead is long past are
dropped as new ones arrive.
"""
from __future__ import annotations

from dataclasses import dataclass

from player_core.drive_readout import DriveHud

# How many entries make it worth scanning for ones to drop.  Housekeeping, not
# a rule about what is true: a turn just behind the playhead is still the one a
# status read lands on, so nothing is dropped while there is no crowd.
_CROWDED = 16


@dataclass(frozen=True)
class DriveKey:
    """The wave a choice was cut from, in the four fields that identify it.

    Everything else about a publish moves every frame; these move only when
    the stroke is really a different stroke -- a control moved the floor, the
    wave realigned after a resume, Genau handed the device over.  A choice
    whose key still matches is a choice made about the wave still running.
    """

    center: float
    amplitude: float
    speed: float
    let_go: float | None

    @classmethod
    def cut_from(cls, published: DriveHud) -> DriveKey:
        return cls(published.center, published.amplitude,
                   published.speed, published.let_go)


@dataclass(frozen=True)
class DescentChoice:
    """How the blue leaves the device at one turn boundary.

    *top* is where the grey ramps down from, *touch* the moment the blue comes
    down onto the park instead -- None for a stroke whose floor sits above it,
    which ramps rather than touching.
    """

    key: DriveKey
    top: float
    touch: int | None


class DescentLatch:
    """The choices a trace is holding, one per approaching turn."""

    def __init__(self) -> None:
        self._choices: dict[int, DescentChoice] = {}

    def choice_for(self, turn_start: int) -> DescentChoice | None:
        """What was chosen for the turn opening at *turn_start*, or None."""
        return self._choices.get(turn_start)

    def remember(self, turn_start: int, choice: DescentChoice, *,
                 stale_before: int) -> None:
        """Hold *choice* for that turn, and let go of turns before
        *stale_before*.

        The dropping rides along with the remembering rather than being a
        second call, because a caller that made the choices and forgot the
        housekeeping would grow this without bound across a session.
        """
        self._choices[turn_start] = choice
        if len(self._choices) > _CROWDED:
            for stale in [turn for turn in self._choices if turn < stale_before]:
                del self._choices[stale]

    def void_all(self) -> None:
        """Let go of every held choice: the wave they were cut from has
        stopped describing this approach."""
        self._choices.clear()
