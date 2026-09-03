"""A boolean two parts of the app share.

Three of Genau's controls are one bit each -- whether the room is paused,
whether the HUD is up, whether Genau owns the screen -- and each was a one-key
mutable dict, a dict whose only purpose was to let a callee move a caller's
variable.  Stringly-keyed, so a typo in the key was a silent no-op rather than
an AttributeError; carrying no invariant; and threaded through three modules
under three different key names ("value", "active", "active").

The edge belonged with them.  The HUD's previous value lived on the refresh
controller while the value itself lived in the box, so the two things that have
to be compared were owned by different objects and the comparison could only be
written where both happened to be in scope.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Flag:
    on: bool = False
    # What was last reported as a move.  Seeded from the value itself, so a flag
    # built already on has not "just moved".
    _reported: bool = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self._reported = self.on

    def moved(self) -> bool:
        """True once each time the flag changes, and False until it changes again.

        Asked by whoever acts on the change -- turning the HUD on is a window
        rebuild, so it must happen on the edge and not every frame.
        """
        if self.on == self._reported:
            return False
        self._reported = self.on
        return True
