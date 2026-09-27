"""The primary display's volume chip: what it shows, and what a press asks for.

Genau's window IS the primary display in genau mode, and reaching for the sound
should not mean finding a different control depending on the mode — so the chip
rides in the clip's row at the foot of the console, where the main player's
does, drawn by the row rather than here.

Genau neither owns the level (Fun Time does, for the whole primary display) nor
plays the sound: a companion process carries the clip music.  What is held here
is only what the chip should show, which is why a press is a question rather
than a move.
"""
from __future__ import annotations

from dataclasses import dataclass

from player_core.volume import VolumeHud


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

    def show(self, level: int, muted: bool) -> None:
        """Show the level Fun Time is publishing for the primary display."""
        self._shown = VolumeHud(volume=level, muted=muted)

    @property
    def shown(self) -> VolumeHud:
        """The level and mute the chip is showing, for the row that draws it."""
        return self._shown

    def pressed_the_speaker(self) -> VolumePress:
        """What a press on the speaker asks for, and what to show meanwhile.

        A question, not a move: it says what to ask Fun Time for *and* what the
        chip should show meanwhile, and the caller does both.  Showing it here
        made a hit test that also mutated, which is why nothing could ask what a
        press would do without it having already happened.
        """
        muted = not self._shown.muted
        return VolumePress(
            command="audio_mute" if muted else "audio_unmute",
            level=self._shown.volume,
            muted=muted,
        )

    @staticmethod
    def pressed_the_slider(level: int) -> VolumePress:
        """What a press that far along the slider asks for.  Reaching for the
        level lifts the mute, as Windows' own mixer does."""
        return VolumePress(
            command=f"audio_set_volume|{level}", level=level, muted=False)
