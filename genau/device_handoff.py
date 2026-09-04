"""The device changing hands, both directions.

Genau drives the device while the hand is playing and lets go of it when it is
not, and the sender is told on that edge, so it can climb out of the park or
walk the stroke down and rest it -- deliberately asymmetric: letting go latches
where the device was, which is the one number the drive readout's trace cannot
recompute afterwards.  The broker is Fun Time's to park and resume.

It is an edge rather than a state.  Told the same thing twice the second says
nothing: a second walk-down would move the latch.
"""
from __future__ import annotations


class DeviceHandoff:
    def __init__(self, *, playing: bool, tcode_sender=None):
        self.tcode_sender = tcode_sender
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
