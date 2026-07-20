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
from dataclasses import dataclass, field

import numpy as np
from genau.drive_hud import DriveHud, DriveSection
from player_core.hud_panel import (
    BG_PRIMARY,
    BLUE,
    BORDER_PANEL,
    GREEN,
    RED,
    TEXT_MUTED,
    TEXT_PRIMARY,
    HudPanel,
    load_font,
    text_width,
)

from .console import (
    Button,
    ConsoleModel,
    Rect,
    console_rows,
    hit_test,
    place_rows,
    row_width,
    rows_height,
    tooltip_at,
)
from .library import FULL, MIXED, SHORTS

# The glyphs the console's buttons are drawn with come from Segoe UI Symbol;
# Segoe UI Bold has none of them and Pillow draws tofu rather than falling back.
SYMBOL_FONT = "seguisym.ttf"

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
    them, and they arrive published.  *active* is whether a bare, player-less
    command lands here rather than on a satellite — drawn as the dot, never as a
    word.
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
_SIZE_TINY = 8
_PAD = 10
DOT = 10      # the active-player dot at the head of the panel
DOT_GAP = 8   # …and the room between it and the words
_MARGIN = 8   # inset from the window's top-left corner
_LINE_GAP = 4
_SECTION_GAP = 8


def hud_xy() -> tuple[int, int]:
    """Where the panel goes: the window's top-left corner, the same place the
    satellites put theirs.

    It used to shift right in Hybrid to clear a panel Genau drew in its own
    transparent layer over this window — with Genau's width hand-copied into a
    constant here, which silently broke Nau's layout whenever that panel was
    resized.  Genau's readout is drawn inside this panel now, so there is nothing
    to clear and nothing to keep in step.
    """
    return _MARGIN, _MARGIN


@dataclass(frozen=True)
class NauHud:
    """Everything on Nau's HUD: what it is playing inside, and the room's controls.

    *modes* is Nau's own answer to "what is selecting this playlist?".  The rest
    arrives from Fun Time — only the orchestrator knows which mode the primary slot
    is in, what is driving the device, or where Genau's controls have hit their
    limits — and *drive* is Genau's live readout, present only while a waveform is
    driving the device.
    """

    modes: ModeHud = field(default_factory=ModeHud)
    console: ConsoleModel = field(default_factory=ConsoleModel)
    drive: DriveHud | None = None


class NauHudPainter:
    """Paints Nau's HUD, and only when something on it has moved.

    Nau redraws its overlays every frame at 60 fps and Pillow is nowhere near
    cheap enough for that, so the bitmap is kept until the panel's contents
    change.  The button rects from the last painting are kept beside it, so what
    is clickable is exactly what was drawn.
    """

    def __init__(self) -> None:
        self._body = load_font(_SIZE_BODY)
        self._tiny = load_font(_SIZE_TINY)
        self._glyph = load_font(_SIZE_BODY, SYMBOL_FONT)
        self._drive = DriveSection()
        self._painted: tuple[NauHud, tuple[int, int] | None] | None = None
        self._bgra: np.ndarray | None = None
        self.buttons: list[tuple[Rect, Button]] = []

    def bgra(self, hud: NauHud, *, hover: tuple[int, int] | None = None) -> np.ndarray:
        """*hud* as an mpv overlay bitmap, with the button under *hover* named.

        The cursor is part of what is drawn, so it is part of what the cache is
        keyed on — otherwise a tooltip would only appear when something else about
        the panel happened to move.
        """
        if (hud, hover) != self._painted or self._bgra is None:
            self._painted, self._bgra = (hud, hover), self._paint(hud, hover)
        return self._bgra

    def command_at(self, mx: int, my: int) -> str:
        """The command a press at *window* point ``(mx, my)`` posts, "" over none.

        The rects were placed from the panel's own corner and presses arrive from
        the window's, so the inset between the two comes off first.  It comes off
        here because this is the only object that knows both numbers: a caller
        undoing `hud_xy` itself is a second copy of where the panel went, free to
        drift from the real one and slide every hit target off what was drawn.
        """
        return hit_test(self.buttons, *self._local(mx, my))

    def hover_at(self, mx: int, my: int) -> tuple[int, int] | None:
        """Where to name the button under *window* point ``(mx, my)``, else None.

        Panel-local, because the tooltip is drawn inside the panel — the HUD lives
        in the video and there is no native tooltip out there to fall back on.
        """
        local = self._local(mx, my)
        return local if tooltip_at(self.buttons, *local) else None

    @staticmethod
    def _local(mx: int, my: int) -> tuple[int, int]:
        """A window point in the panel's own coordinates."""
        left, top = hud_xy()
        return mx - left, my - top

    def _paint(self, hud: NauHud, hover: tuple[int, int] | None = None) -> np.ndarray:
        rows = console_rows(hud.console)
        lines = [line for line in (hud.modes.line, hud.console.osr2) if line]
        line_h = sum(self._body.getmetrics())
        drive_w, drive_h = DriveSection.SIZE if hud.drive is not None else (0, 0)

        dotted = DOT + DOT_GAP
        width = 2 * _PAD + max(
            [row_width(rows), drive_w]
            + [dotted + text_width(self._body, line) for line in lines])
        # The dot's own line is there even with nothing to say beside it.
        height = 2 * _PAD + rows_height(rows) + _SECTION_GAP
        height += max(1, len(lines)) * (line_h + _LINE_GAP) - _LINE_GAP
        if hud.drive is not None:
            height += drive_h + _SECTION_GAP

        panel = HudPanel(width, height)
        draw = panel.draw
        y = _PAD
        # Green while a bare, player-less command lands here, the palette's grey
        # otherwise — the same dot, in the same corner, as each satellite's.  It
        # leads the first line and is drawn whether or not there is a line: a dot
        # that vanished when the player had nothing else to say could not be told
        # from one saying the floor is elsewhere.
        draw.ellipse([_PAD, y + 2, _PAD + DOT, y + 2 + DOT],
                     fill=(*(GREEN if hud.modes.active else TEXT_MUTED), 255))
        text_x = _PAD + DOT + DOT_GAP
        for line in lines:
            draw.text((text_x, y + line_h), line, font=self._body, anchor="ls",
                      fill=(*TEXT_PRIMARY, 255))
            y += line_h + _LINE_GAP
        y += (_SECTION_GAP - _LINE_GAP) if lines else line_h + _SECTION_GAP - _LINE_GAP

        self.buttons = place_rows(rows, x=_PAD, y=y)
        for rect, button in self.buttons:
            self._button(draw, rect, button)
        y += rows_height(rows)

        if hud.drive is not None:
            # Drawn into this panel rather than beside it: the controls above are
            # what move these numbers, and a reading that lived on its own slab
            # would be a second HUD to find rather than the answer to the row you
            # just pressed.
            self._drive.draw(draw, _PAD, y + _SECTION_GAP, hud.drive)

        if hover is not None:
            self._tooltip(draw, width, height, tooltip_at(self.buttons, *hover), hover)
        return panel.to_bgra()

    def _tooltip(self, draw, width: int, height: int, text: str, pos: tuple[int, int]) -> None:
        """A tooltip drawn inside the panel near the cursor — the HUD lives in the
        video, so there is no native one to fall back on, and every glyph up here
        is cryptic on purpose."""
        if not text:
            return
        pad = 5
        ascent, descent = self._tiny.getmetrics()
        w = text_width(self._tiny, text) + 2 * pad
        h = ascent + descent + 2 * pad
        x = max(2, min(pos[0] + 14, width - w - 2))
        y = max(2, min(pos[1] + 16, height - h - 2))
        draw.rounded_rectangle([x, y, x + w - 1, y + h - 1], radius=4,
                               fill=(*BG_PRIMARY, 240), outline=(*BORDER_PANEL, 255), width=1)
        draw.text((x + w / 2, y + h / 2), text, font=self._tiny, anchor="mm",
                  fill=(*TEXT_PRIMARY, 255))

    def _button(self, draw, rect: Rect, button: Button) -> None:
        """One control, in the one button shape this family's HUDs are drawn with:
        an outline when off, filled when on, faded when it has run out of range.

        A label — an item with nothing to post — is drawn as a bare word instead,
        because a box around it would invite a press that does nothing.
        """
        x, y, w, h = rect
        if not button.action:
            draw.text((x + w, y + h / 2), button.glyph, font=self._tiny, anchor="rm",
                      fill=(*TEXT_MUTED, 255))
            return
        fill = GREEN if button.lit else RED if button.warn else BLUE if button.hold else None
        edge = TEXT_MUTED if button.dim else (fill or TEXT_MUTED)
        draw.rounded_rectangle([x, y, x + w - 1, y + h - 1], radius=3,
                               fill=(*fill, 255) if fill else None,
                               outline=(*edge, 255), width=1)
        # A word rides the UI face; a symbol needs the face that actually has it.
        font = self._tiny if button.glyph.isalnum() else self._glyph
        ink = BG_PRIMARY if fill else TEXT_MUTED if button.dim else TEXT_PRIMARY
        draw.text((x + w / 2, y + h / 2), button.glyph, font=font, anchor="mm",
                  fill=(*ink, 255))
