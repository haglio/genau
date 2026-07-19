"""Nau's mode HUD: a standing answer to "what am I inside?".

Nau's window says what is playing but never what is *selecting* it, so the
library mode and a compilation playlist were both invisible — you could be held
inside one volume's clips with nothing on screen saying so, and no way to guess
which words got you out.  This is the panel that says it.

The wording and the shape are pure functions here; the drawing goes onto the
slab :mod:`player_core.hud_panel` owns, which is the same slab the satellites'
HUD is drawn on, so the two players say things the same way.

The transient counterpart is :mod:`nau.notice` — a message Fun Time flashes
once.  This one persists, because a mode you are in is not news, it is a state.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
from player_core.hud_panel import GREEN, TEXT_MUTED, TEXT_PRIMARY, HudPanel, load_font, text_width

from .library import FULL, SHORTS
from .overlay import CORNER_MARGIN, INDICATOR_BOX

# What the length modes are called on screen.  The library names them for what
# it filters on; the HUD names them for what the user asked for.
_LENGTH_LABELS = {FULL: "Full length", SHORTS: "Shorts"}

# A compilation is titled for a shelf: "various - Ultimate Example Studio
# Alpha Collection - Volume 6 (v1)".  Everything up to the last dash is the
# series — identical across every volume, so it tells the viewer nothing — and
# the trailing "(v1)" is the archivist's revision, leaving the volume as the only
# part that says which one you are inside.
_REVISION = re.compile(r"\s*\(v\d+\)$")


def compilation_label(title: str) -> str:
    """*title* cut down to what tells one compilation from another."""
    volume = title.rsplit(" - ", 1)[-1]
    return _REVISION.sub("", volume).strip()


@dataclass(frozen=True)
class ModeHud:
    """The modes the player is in, ready to be drawn.

    *length_mode* is the library's own filter and is empty when there is no
    library behind the playlist at all (Fun Time can hand Nau a playlist without
    one), in which case there is no length mode to claim.  *compilation* is the
    volume whose clips are the playlist, empty while the library is feeding it
    normally; *position* and *total* place the current video in that playlist.
    """

    length_mode: str = ""
    compilation: str = ""
    position: int = 0
    total: int = 0

    @property
    def lines(self) -> tuple[str, ...]:
        """The panel's text, top line first."""
        lines = []
        label = _LENGTH_LABELS.get(self.length_mode)
        if label:
            lines.append(label)
        if self.compilation:
            lines.append(f"{compilation_label(self.compilation)} · {self.position}/{self.total}")
        return tuple(lines)


# --- the panel ---------------------------------------------------------------

_SIZE_BODY = 11
_PAD = 10
_LINE_GAP = 3
_DOT = 10       # diameter of the held/browsing dot
_DOT_GAP = 8    # between the dot and the text column
_UNDER_INDICATOR = 6  # clearance below the state icon the panel hangs from


def hud_xy(win_w: int, panel_w: int) -> tuple[int, int]:
    """Where the panel goes: the top-right corner, tucked under the state
    indicator, so the two share an edge and neither crosses the video's middle.
    The top left is already the video's name and playback rate."""
    return win_w - panel_w - CORNER_MARGIN, CORNER_MARGIN + INDICATOR_BOX + _UNDER_INDICATOR


class ModeHudPainter:
    """Paints a :class:`ModeHud`, and only when what it says changes.

    Nau redraws its overlays every frame at 60 fps and Pillow is nowhere near
    cheap enough for that, so the bitmap is kept until the modes move — which is
    a few times an hour.
    """

    def __init__(self) -> None:
        self._font = load_font(_SIZE_BODY)
        self._painted: ModeHud | None = None
        self._bgra: np.ndarray | None = None

    def bgra(self, hud: ModeHud) -> np.ndarray | None:
        """*hud* as an mpv overlay bitmap, or None when it has nothing to say."""
        if hud != self._painted:
            self._painted, self._bgra = hud, self._paint(hud)
        return self._bgra

    def _paint(self, hud: ModeHud) -> np.ndarray | None:
        lines = hud.lines
        if not lines:
            return None
        ascent, descent = self._font.getmetrics()
        line_h = ascent + descent
        text_x = _PAD + _DOT + _DOT_GAP
        panel = HudPanel(
            text_x + max(text_width(self._font, line) for line in lines) + _PAD,
            2 * _PAD + len(lines) * line_h + (len(lines) - 1) * _LINE_GAP,
        )
        # The dot rides the first line, the way the satellite's lock dot rides its
        # label: green while a compilation is holding the playlist, grey while the
        # library is simply feeding it.
        dot_y = _PAD + (line_h - _DOT) // 2
        panel.draw.ellipse(
            [_PAD, dot_y, _PAD + _DOT, dot_y + _DOT],
            fill=(*(GREEN if hud.compilation else TEXT_MUTED), 255),
        )
        y = _PAD
        for line in lines:
            panel.draw.text((text_x, y + ascent), line, font=self._font, anchor="ls",
                            fill=(*TEXT_PRIMARY, 255))
            y += line_h + _LINE_GAP
        return panel.to_bgra()
