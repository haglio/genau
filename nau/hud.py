"""Nau's mode HUD: a standing answer to "what am I inside?".

Nau's window says what is playing but never what is *selecting* it, so the
library mode and a compilation playlist were both invisible — you could be held
inside one volume's clips with nothing on screen saying so, and no way to guess
which words got you out.  This is the panel that says it.

One thing is *selecting* the playlist at any moment — the volume holding it if
you are inside one, otherwise the length mode the library is feeding it through —
and that is the first thing it says.  Fun Time's F-mode then sits over whichever
of those is running, narrowing it to the scripted videos, so it rides alongside
rather than replacing.

The dot at its head answers a different question — whether a bare, player-less
command lands here or on a satellite — and so it is drawn even when there is no
mode to name: an absent dot cannot be told from an idle one, and the whole point
of it is being readable on the player that does *not* have the floor.

The wording and the shape are pure functions here; the drawing goes onto the
slab :mod:`player_core.hud_panel` owns, which is the same slab the satellites'
HUD is drawn on, so the two players say things the same way — and from the same
corner.

The transient counterpart is :mod:`nau.notice` — a message Fun Time flashes
once.  This one persists, because a mode you are in is not news, it is a state.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
from player_core.hud_panel import (
    GREEN,
    TEXT_MUTED,
    TEXT_PRIMARY,
    HudPanel,
    load_font,
    text_width,
)

from .library import FULL, MIXED, SHORTS

# What the length modes are called on screen.  The library names them for what
# it filters on; the HUD names them for what the user asked for.
_LENGTH_LABELS = {MIXED: "Mixed", FULL: "Full length", SHORTS: "Shorts"}

# What F-mode is called on screen.  One Fun Time key toggles it for every player
# at once, so it has to read the same here as it does on the satellites' HUD —
# ``fun_time.lock_hud.F_MODE_LABEL`` is the other half of that pair, and the one
# place the wording could drift.
F_MODE_LABEL = "F-Mode"

_SEPARATOR = " · "

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
    """The mode the player is in, ready to be drawn.

    *length_mode* is the library's own filter and is empty when there is no
    library behind the playlist at all (Fun Time can hand Nau a playlist without
    one), in which case there is no length mode to claim.  *compilation* is the
    volume whose clips are the playlist, empty while the library is feeding it
    normally; *position* and *total* place the current video in that playlist.
    *f_mode* and *active* are Fun Time's, not Nau's: only the orchestrator knows
    them, and they arrive over the command channel like the hybrid flag does.
    *active* is whether a bare, player-less command lands here rather than on a
    satellite — drawn as the dot, never as a word.
    """

    length_mode: str = ""
    compilation: str = ""
    position: int = 0
    total: int = 0
    f_mode: bool = False
    active: bool = False

    @property
    def line(self) -> str:
        """The panel's text — empty when there is nothing to say.

        A compilation answers the "what is selecting this?" question on its own:
        the volume and the place in it are what you are inside, and the length
        filter running behind them is not, so naming it too would only be noise.

        F-mode is not an answer to that question but a filter over whatever the
        answer is, so it goes on the end of either — and stands alone when Nau is
        playing a handed-over playlist with no library and no volume behind it,
        which is the one case where it is the only thing true of the playlist.
        """
        parts = []
        if self.compilation:
            parts.append(
                f"{compilation_label(self.compilation)}{_SEPARATOR}{self.position}/{self.total}"
            )
        elif self.length_mode in _LENGTH_LABELS:
            parts.append(_LENGTH_LABELS[self.length_mode])
        if self.f_mode:
            parts.append(F_MODE_LABEL)
        return _SEPARATOR.join(parts)


# --- the panel ---------------------------------------------------------------

_SIZE_BODY = 11
PAD = 10
DOT = 10      # the active-player dot at the head of the panel
DOT_GAP = 8   # …and the room between it and the words
_MARGIN = 8   # inset from the window's top-left corner

# Genau draws its own panel (waveform, speed, amplitude) at the same inset in its
# own window.  In Hybrid that window is a transparent layer over Nau's, so the
# two would sit on top of each other; Nau's starts past Genau's instead.  The
# width is Genau's panel's, kept as a constant rather than imported, because
# Nau must not reach into Genau's rendering to lay out its own corner.
GENAU_PANEL_W = 200
_GENAU_GAP = 8


def hud_xy(*, hybrid: bool) -> tuple[int, int]:
    """Where the panel goes: the window's top-left corner, the same place the
    satellites put theirs — shifted clear of Genau's panel in Hybrid."""
    return _MARGIN + (GENAU_PANEL_W + _GENAU_GAP if hybrid else 0), _MARGIN


class ModeHudPainter:
    """Paints a :class:`ModeHud`, and only when what it says changes.

    Nau redraws its overlays every frame at 60 fps and Pillow is nowhere near
    cheap enough for that, so the bitmap is kept until the mode moves — which is
    a few times an hour.
    """

    def __init__(self) -> None:
        self._font = load_font(_SIZE_BODY)
        self._painted: ModeHud | None = None
        self._bgra: np.ndarray | None = None


    def bgra(self, hud: ModeHud) -> np.ndarray:
        """*hud* as an mpv overlay bitmap.

        Always a bitmap now, never None: the dot is on it, and a dot that
        disappears when the player has nothing else to say cannot be told from an
        idle one — which would leave only the player *holding* the floor saying
        anything, and no way to read that off this one.
        """
        if hud != self._painted:
            self._painted, self._bgra = hud, self._paint(hud)
        return self._bgra

    def _paint(self, hud: ModeHud) -> np.ndarray:
        line = hud.line
        ascent, descent = self._font.getmetrics()
        text_x = PAD + DOT + DOT_GAP
        panel = HudPanel(
            text_x + text_width(self._font, line) + PAD,
            2 * PAD + ascent + descent,
        )
        # Green while a bare command lands here, the palette's grey otherwise —
        # the same dot, in the same place, as each satellite's.
        panel.draw.ellipse(
            [PAD, PAD + 2, PAD + DOT, PAD + 2 + DOT],
            fill=(*(GREEN if hud.active else TEXT_MUTED), 255),
        )
        if line:
            panel.draw.text((text_x, PAD + ascent), line, font=self._font, anchor="ls",
                            fill=(*TEXT_PRIMARY, 255))
        return panel.to_bgra()
