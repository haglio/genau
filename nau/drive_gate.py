"""What of Genau's publish this video's picture is allowed to believe.

:mod:`nau.drive_trace` draws one line out of two drivers, and two of the things
it needs cannot be read off a single publish:

*The descent forecasts.*  A descent's top is SELECTED once per approaching turn
and then held, because re-read live every frame it breathed with the beat
between Genau's publish cadence and the frame clock, and the seam flickered.
Holding one means knowing when it is void — and it is void whenever the wave it
was cut from stopped describing this approach: a stint with nobody behind the
screen, a different video, a seek, or a pause long enough for the media clock
and the wall clock to part company.

*Who has the device.*  ``DriveHud.let_go`` is Genau's own latch of the height it
handed over at, and it describes the last handoff GENAU made — which, across a
video change while it sits paused, is a handoff from some other video's stroke.
A descent drawn from that height tops a ramp the device never made here.  So it
is honoured only once Genau has been seen live (``let_go`` unset) within the
current video; until then the descent tops off the parked publish instead, which
is where the device really is.

Lived as a closure and two dicts inside ``nau.app``'s run loop, where none of
these rules could be exercised: widening the seek window a hundredfold, so a
rewind no longer voided the held forecasts, left the whole suite green.
"""
from __future__ import annotations

from dataclasses import replace

from player_core.drive_readout import DriveHud

from .drive_trace import drive_readout
from .status import next_handoff_touch

# What counts as a seek rather than a frame's worth of playing.  Real frames
# advance tens of milliseconds (and the trace's 40ms quantum makes some read as
# zero); anything outside this is a jump.  Asymmetric because a rewind is a
# rewind at once, while forward motion has to allow for a slow frame.
#
# Any seek voids every held choice: the carry rules are written for one
# continuous approach, and a rewind approaches the SAME boundary again with a
# realigned wave — the old choice's touch cuts the new wave anywhere, and the
# blue overruns its own drawn ending by a whole cycle.
_REWIND_MS = -250
_JUMP_AHEAD_MS = 400

# How many frames of a standing playhead make a real pause rather than the
# quantum reading as zero.  When one ends, the media clock has stood still while
# Genau's wave kept moving in wall time, so every media-anchored forecast slid
# off the wave it was cut from.
_STALLED_FRAMES = 25


class DriveGate:
    """The forecasts this trace is holding, and the rules that void them."""

    def __init__(self, session) -> None:
        self._session = session
        # One entry per approaching turn: (key, top, touch-down).  Written by
        # drive_readout, read by the status file, cleared here.
        self._tops: dict = {}
        self._video = None
        self._seen_live = False
        self._position = 0
        self._stalled = 0

    def readout(self, published: DriveHud | None, *, genau_behind: bool) -> DriveHud:
        """The readout to draw, with this video's funscript folded into it.

        *published* is Genau's readout as it last said it; *genau_behind* says
        whether Genau is there to take the gaps at all.  In Nau's own mode there
        is no Genau behind the screen, and nothing published is believed.
        """
        drive = published if genau_behind else None
        position = int(self._session.position_ms)
        if drive is None:
            # A stint without Genau behind the screen: the wave keeps moving
            # while nothing here watches it, so every held forecast is void by
            # the time it could be read again.
            self._tops.clear()
        if drive is not None:
            if self._video != self._session.current_video:
                self._video = self._session.current_video
                self._seen_live = False
                self._tops.clear()
            moved = position - self._position
            if moved < _REWIND_MS or moved > _JUMP_AHEAD_MS:
                self._tops.clear()
                self._stalled = 0
            elif moved == 0:
                self._stalled += 1
            else:
                if self._stalled > _STALLED_FRAMES:
                    self._tops.clear()
                self._stalled = 0
            if drive.let_go is None:
                self._seen_live = True
            elif not self._seen_live:
                drive = replace(drive, let_go=None)
        self._position = position
        return drive_readout(
            drive,
            script=self._session.current_funscript,
            position_ms=position,
            speed=self._session.speed,
            genau_behind=genau_behind,
            descent_tops=self._tops,
        )

    def handoff_touch(self) -> int | None:
        """The touch-down the trace has chosen for the boundary in play.

        Published with every status so the arbiter ends Genau's turn where the
        picture drew it ending; see :func:`nau.status.next_handoff_touch` for
        why there is one chooser rather than two.
        """
        return next_handoff_touch(
            self._session.current_funscript,
            int(self._session.position_ms), self._tops)
