"""Nau's volume control: the level on screen, and where a press on it lands.

Fun Time holds the authoritative level and mute for the whole primary display —
Nau's own video and Genau's clip audio are two sinks of one loudness — so this
draws that state and reports presses; it never decides the level itself.

The one thing it needs that the sinks do not is the *mute* as a fact of its own.
Fun Time publishes a mute to the sinks as a level of zero, which is right for
something that only has to be quiet, and useless for something that has to say
whether you are muted or merely turned all the way down.  So the level and the
mute both arrive here, and the audible loudness is derived rather than sent.

Geometry and hit-testing are pure functions with no Pillow, the way
:mod:`satellite.hud` keeps its layout testable without a font.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from player_core.hud_panel import (
    BG_PRIMARY,
    BORDER_PANEL,
    TEXT_MUTED,
    TEXT_PRIMARY,
    to_bgra,
)
from PIL import Image, ImageDraw

# The chip: a speaker at the left end, a slider filling the rest.  Sized for the
# corner of a video rather than for a mouse-heavy toolbar — big enough to hit,
# small enough to ignore.
CHIP_W = 112
CHIP_H = 22
MARGIN = 10          # inset from the window's right edge and from the timeline
SPEAKER_W = 26       # the left end that toggles the mute
PAD = 6
TRACK_H = 4

MIN_VOLUME = 0
MAX_VOLUME = 100


def chip_xy(*, win_w: int, win_h: int, timeline_h: int) -> tuple[int, int]:
    """Where the chip sits: the right-hand end of the row above the timeline.

    Beside the transport rather than up in the top-left column, which belongs to
    the furniture that says what is *selecting* the video.  Clamped at the left so
    a narrow window shrinks the margin instead of pushing the chip off screen.
    """
    return max(0, win_w - CHIP_W - MARGIN), max(0, win_h - timeline_h - CHIP_H - MARGIN)


# --- hit-testing -------------------------------------------------------------

_TRACK_X0 = SPEAKER_W
_TRACK_X1 = CHIP_W - PAD


def hit_part(x: int, y: int) -> str:
    """Which control a press at chip-local ``(x, y)`` is on: "mute", "track", or
    "" for neither.  The speaker takes the left end and the slider the rest, so
    every pixel of the chip does something and none of it is decoration."""
    if not (0 <= x < CHIP_W and 0 <= y < CHIP_H):
        return ""
    return "mute" if x < SPEAKER_W else "track"


def volume_at(x: int) -> int:
    """The level a press at chip-local *x* asks for, clamped to the track's ends.

    Past either end saturates rather than doing nothing: dragging off the chip
    should pin the level at silent or full, which is what the pointer is asking
    for, not abandon the drag mid-way.
    """
    span = max(1, _TRACK_X1 - _TRACK_X0)
    fraction = (x - _TRACK_X0) / span
    return int(round(min(1.0, max(0.0, fraction)) * MAX_VOLUME))


# --- what it shows -----------------------------------------------------------


@dataclass(frozen=True)
class VolumeHud:
    """The level Fun Time is publishing, and whether it is muted there."""

    volume: int = MAX_VOLUME
    muted: bool = False


_MUTED_BAR = (200, 70, 70)   # the slash across a muted speaker


def _draw_speaker(draw: ImageDraw.ImageDraw, muted: bool) -> None:
    """A speaker cone at the left end, struck through while muted.

    Drawn rather than typed: the glyph fonts differ on the trailing waves, and a
    missing one draws a tofu box where the clearest control on the chip should be.
    """
    colour = TEXT_MUTED if muted else TEXT_PRIMARY
    mid = CHIP_H // 2
    x = PAD
    draw.rectangle([x, mid - 3, x + 4, mid + 3], fill=(*colour, 255))
    draw.polygon([(x + 4, mid - 3), (x + 10, mid - 7), (x + 10, mid + 7), (x + 4, mid + 3)],
                 fill=(*colour, 255))
    if muted:
        draw.line([(x, mid + 7), (x + 13, mid - 7)], fill=(*_MUTED_BAR, 255), width=2)


class VolumeHudPainter:
    """Paints a :class:`VolumeHud`, and only when what it shows changes.

    Nau redraws its overlays every frame at 60fps; the level moves a few times a
    session, so the bitmap is kept until it does.
    """

    def __init__(self) -> None:
        self._painted: VolumeHud | None = None
        self._bgra: np.ndarray | None = None

    def bgra(self, hud: VolumeHud) -> np.ndarray:
        if hud != self._painted:
            self._painted, self._bgra = hud, self._paint(hud)
        return self._bgra

    def _paint(self, hud: VolumeHud) -> np.ndarray:
        image = Image.new("RGBA", (CHIP_W, CHIP_H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle([0, 0, CHIP_W - 1, CHIP_H - 1], radius=CHIP_H // 2,
                               fill=(*BG_PRIMARY, 200), outline=(*BORDER_PANEL, 255), width=1)
        _draw_speaker(draw, hud.muted)
        mid = CHIP_H // 2
        draw.rounded_rectangle(
            [_TRACK_X0, mid - TRACK_H // 2, _TRACK_X1, mid + TRACK_H // 2],
            radius=TRACK_H // 2, fill=(*TEXT_MUTED, 255),
        )
        # The fill stays put under a mute: the level is what unmuting returns to,
        # so hiding it would lose the only record of where the speaker was set.
        level = min(MAX_VOLUME, max(MIN_VOLUME, hud.volume))
        filled = _TRACK_X0 + round((_TRACK_X1 - _TRACK_X0) * level / MAX_VOLUME)
        if filled > _TRACK_X0:
            draw.rounded_rectangle(
                [_TRACK_X0, mid - TRACK_H // 2, filled, mid + TRACK_H // 2],
                radius=TRACK_H // 2, fill=(*TEXT_PRIMARY, 255),
            )
        return to_bgra(image)
