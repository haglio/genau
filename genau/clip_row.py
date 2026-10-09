"""The clip's row at the console's foot: its time on screen on the track, its loop on the dial.

A clip has two senses of time.  The track is a scrubber, so it runs how long
the clip has been up of the turn it gets before the next one arrives; the loop
of the clip itself has no start or end to scrub between, so it goes round the
dial beside the track, once per turn.
"""
from __future__ import annotations

from player_core.hud_row import RowHud
from player_core.playhead import video_playhead
from player_core.volume import VolumeHud


class ClipRow:
    """What the row shows, read off the renderer showing the frames and the
    clip advance timing the switch.

    Built beside the console and the volume chip, so what is drawn is one object
    the app wires -- but told what to follow afterwards, because the renderer is
    built around the view and cannot be handed to it first.
    """

    def __init__(self) -> None:
        self._renderer = None
        self._clip_advance = None

    def follow(self, renderer, clip_advance) -> None:
        self._renderer = renderer
        self._clip_advance = clip_advance

    def hud(self, volume: VolumeHud) -> RowHud | None:
        """The row for the clip on screen, or None while there is none."""
        turn = self.loop_turn()
        if turn is None:
            return None
        elapsed_ms = self._clip_advance.elapsed * 1000.0
        return RowHud(position_ms=elapsed_ms, duration_ms=self.interval_ms, volume=volume,
                      playhead=video_playhead(elapsed_ms, self.interval_ms, 0),
                      loop_turn=turn)

    @property
    def interval_ms(self) -> float:
        return self._clip_advance.interval * 1000.0

    def loop_turn(self) -> float | None:
        """How far round its loop the clip has gone, 0 to 1; None before a frame is up."""
        return self._renderer.loop_turn if self._renderer is not None else None
