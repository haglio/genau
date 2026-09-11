"""The primary display's volume chip, in the corner the main player puts it in.

Genau's window IS the primary display in genau mode, and reaching for the sound
should not mean finding a different control depending on the mode — so the chip
sits in the same pixels the main player's does, drawn by the same painter.

Genau neither owns the level (Fun Time does, for the whole primary display) nor
plays the sound: a companion process carries the clip music.  What is held here
is only what the chip should show, which is why a press is a question rather
than a move.
"""
from __future__ import annotations

from dataclasses import dataclass

from player_core.volume import (
    VolumeHud,
    VolumeHudPainter,
    chip_local,
    chip_xy,
    hit_part,
    volume_at,
)


@dataclass(frozen=True)
class VolumePress:
    """What a press on the volume chip asks for, and what to show meanwhile.

    Fun Time holds the authority over the level and its answer is a tick away,
    so a slider that waited for it would trail the pointer by a frame.  The
    chip shows this at once; Fun Time's answer overwrites it either way, which
    is what corrects a press it decides to ignore.
    """

    command: str
    level: int
    muted: bool


class VolumeChip:
    def __init__(self) -> None:
        self._shown = VolumeHud()
        self._painter = VolumeHudPainter()

    def show(self, level: int, muted: bool) -> None:
        """Show the level Fun Time is publishing for the primary display."""
        self._shown = VolumeHud(volume=level, muted=muted)

    def press_at(self, mx: int, my: int, *, win_w: int, win_h: int,
                 ) -> VolumePress | None:
        """What a press at ``(mx, my)`` asks for, or None over no part of the chip.

        A question, not a move: it says what to ask Fun Time for *and* what the
        chip should show meanwhile, and the caller does both.  Showing it here
        made a hit test that also mutated, which is why nothing could ask what a
        press would do without it having already happened.
        """
        cx, cy = chip_local(mx, my, win_w=win_w, win_h=win_h, timeline_h=0)
        part = hit_part(cx, cy)
        if part == "mute":
            muted = not self._shown.muted
            return VolumePress(
                command="audio_mute" if muted else "audio_unmute",
                level=self._shown.volume,
                muted=muted,
            )
        if part == "track":
            level = volume_at(cx)
            return VolumePress(
                command=f"audio_set_volume|{level}", level=level, muted=False)
        return None

    def rgba(self) -> tuple[bytes, tuple[int, int]]:
        return self._painter.rgba(self._shown)

    @staticmethod
    def corner(*, win_w: int, win_h: int) -> tuple[int, int]:
        """Where the chip goes in a window of this size.

        ``timeline_h=0`` says there is no scrubber under it, which is what this
        window has and the main player's does not; the chip still lands in the same pixels
        The main player's does.
        """
        return chip_xy(win_w=win_w, win_h=win_h, timeline_h=0)
