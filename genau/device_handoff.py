"""The device changing hands, both directions.

Genau drives the device while the hand is playing and lets go of it when it is
not, and two separate things have to happen on that edge.  The sender is told,
so it can climb out of the park or walk the stroke down and rest it -- and that
is deliberately asymmetric: letting go latches where the device was, which is
the one number the drive readout's trace cannot recompute afterwards.  The
broker is told too, so the room's other player can take the device over.

Both are edges rather than states.  Told the same thing twice the second says
nothing: a second walk-down would move the latch, and the broker file would
otherwise be rewritten a hundred times a second for a fact that changes twice a
session.
"""
from __future__ import annotations

from pathlib import Path


class DeviceHandoff:
    def __init__(
        self,
        *,
        playing: bool,
        tcode_sender=None,
        broker_cmd_file: Path | None = None,
    ):
        self.tcode_sender = tcode_sender
        # Absent under Fun Time, which parks the broker itself: two players
        # writing that file would fight over one device.
        self.broker_cmd_file = broker_cmd_file
        # Seeded from the state itself, so a PAUSE queued before the first tick
        # reads as a real falling edge against the state this was built in.
        self._playing = playing

    def watch(self, playing: bool) -> None:
        was, self._playing = self._playing, playing
        if playing == was:
            return
        if self.tcode_sender is not None:
            if playing:
                self.tcode_sender.take_over()
            else:
                self.tcode_sender.hand_over()
        if self.broker_cmd_file is not None:
            self.broker_cmd_file.write_text(
                "RESUME" if playing else "PARK", encoding="utf-8",
            )
