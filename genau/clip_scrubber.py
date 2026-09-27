"""Where the clip has got to, for the row the console carries at its foot.

Drawn along the window's lower edge until 2026-09-26, the way a video player
has always drawn one.  One panel per screen: the track, the frame count and
the volume chip are a block of the console now
(:mod:`player_core.hud_row`), which is where the headset has drawn the main
player's since the wrap smeared a row over the picture round the nadir.
"""
from __future__ import annotations

from player_core.hud_row import RowHud
from player_core.playhead import PlayheadHud, clip_playhead
from player_core.timeline import bar_track_x
from player_core.volume import VolumeHud


class ClipScrubber:
    """What the track shows, read off the renderer that is showing the frames.

    Built beside the console and the volume chip, so what is drawn is one object
    the app wires -- but told its renderer afterwards, because the renderer is
    built around the view and cannot be handed to it first.
    """

    def __init__(self) -> None:
        self._renderer = None

    def follow(self, renderer) -> None:
        self._renderer = renderer

    def row(self, volume: VolumeHud) -> RowHud | None:
        """The row for the clip on screen, or None while there is none.

        Counted in frames rather than milliseconds -- a clip is a loop of
        frames and has no running time -- so the track maps the frame the
        motion has reached against how many there are.
        """
        played, of = self.playhead()
        if of <= 0:
            return None
        return RowHud(position_ms=played, duration_ms=of, volume=volume,
                      playhead=self.readout())

    def playhead(self) -> tuple[int, int]:
        """How far through the clip the motion has taken it, of how far there is
        to go; (0, 0) before any clip is up.

        Counted UP, which the frame that is up is not: player_core shows a clip
        from its last frame back (clip_renderer.display_index_for_phase), so a
        cursor drawn straight off that index walked backwards along the bar.
        """
        if self._renderer is None:
            return (0, 0)
        entry = self._renderer.current_clip_entry()
        frames = entry.get("frames") if entry else None
        count = len(frames) if frames else 0
        index = self._renderer.current_frame_index
        return (0 if index is None else max(0, count - 1 - index), count)

    def readout(self) -> PlayheadHud | None:
        return clip_playhead(*self.playhead())

    @staticmethod
    def fraction_at(px: int, *, width: int) -> float:
        """How far along a track *width* across a press at *px* is, saturating
        past either end."""
        x0, x1 = bar_track_x(width)
        return min(1.0, max(0.0, (px - x0) / max(1, x1 - x0)))
