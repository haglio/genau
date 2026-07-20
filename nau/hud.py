"""The primary console — the HUD the player on the primary slot draws.

Fun Time's dashboard used to draw a schematic of the two monitors and hang the
primary's controls off it.  The primary player draws them itself now, and the
same console is drawn whichever player holds the slot: Nau over its video in nau
and hybrid, Genau into its own window in genau.  So the mode switch and the drive
controls keep their places as you flip between modes — only the transport changes,
because it steps Nau's video in one and Genau's clips in the other.

Its top line is Nau's own answer to "what am I inside?" — the length mode or the
compilation, with the active-player dot at its head — and it is empty in genau
mode, where there is no Nau playlist behind the screen.  Everything else is the
console the orchestrator publishes (:mod:`nau.console`) plus, while Genau is
driving, the drive readout (:mod:`genau.drive_hud`) with its own arrows.

The wording and shape are pure functions; the drawing goes onto the slab
:mod:`player_core.hud_panel` owns, the same slab the satellites' HUD is drawn on,
so every player says things the same way and from the same corner.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

import numpy as np
from PIL import Image
from genau.drive_hud import DriveHud, DriveSection
from genau.drive_hud import controls as drive_controls
from player_core.hud_panel import (
    AMBER,
    BG_PRIMARY,
    BLUE,
    BORDER_PANEL,
    GREEN,
    RED,
    TEXT_MUTED,
    TEXT_PRIMARY,
    WHITE,
    HudPanel,
    load_font,
    text_width,
    to_bgra,
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

# What the length modes are called on screen.  The library names them for what it
# filters on; the HUD names them for what the user asked for.
_LENGTH_LABELS = {MIXED: "Mixed", FULL: "Full length", SHORTS: "Shorts"}

# What F-mode is called on screen.  One Fun Time key toggles it for every player
# at once, so it reads the same here as on the satellites' HUD.
F_MODE_LABEL = "F-Mode"

_SEPARATOR = " · "

# A compilation is titled for a shelf: "various - Ultimate Example Studio Alpha
# Collection - Volume 6 (v1)".  Everything up to the last dash is the series and
# the trailing "(v1)" the archivist's revision, leaving the volume as the part
# that says which one you are inside.
_REVISION = re.compile(r"\s*\(v\d+\)$")

# What the OSR2 line says by what is driving the device, and the colour it says
# it in — green when a funscript is driving, blue when Genau is, muted when
# nothing is, amber for the broker's own auto mode.
_OSR2_LABELS = {
    "off": "Off", "auto": "Auto", "funscript": "FunScript",
    "genau": "Genau", "idle": "Idle",
}
_OSR2_COLORS = {
    "funscript": GREEN, "genau": BLUE, "auto": AMBER,
    "off": TEXT_MUTED, "idle": TEXT_MUTED,
}

# The drive readout's own arrows are drawn by the readout, but the console still
# has to know what each posts and name it on hover.
_DRIVE_TIPS = {
    "genau_speed_down": "Stroke slower", "genau_speed_up": "Stroke faster",
    "genau_amplitude_up": "Amplitude up", "genau_amplitude_down": "Amplitude down",
    "genau_center_up": "Center up", "genau_center_down": "Center down",
}


def compilation_label(title: str) -> str:
    """*title* cut down to what tells one compilation from another."""
    volume = title.rsplit(" - ", 1)[-1]
    return _REVISION.sub("", volume).strip()


@dataclass(frozen=True)
class ModeHud:
    """Nau's own answer to "what is selecting this playlist?" — the top line.

    *length_mode* is the library's filter, empty when there is no library behind
    the playlist; *compilation* is the volume holding the playlist, with
    *position*/*total* placing the current video in it.  *f_mode* is Fun Time's
    filter over whichever of those runs.  All empty in genau mode, where there is
    no Nau playlist to describe.
    """

    length_mode: str = ""
    compilation: str = ""
    position: int = 0
    total: int = 0
    f_mode: bool = False

    @property
    def line(self) -> str:
        """The top line's text — empty when there is nothing to say."""
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
DOT = 10       # the active-player dot at the head of the top line
DOT_GAP = 8    # …and the room between it and the words
_MARGIN = 8    # inset from the window's top-left corner
_ROW_GAP = 4   # between the top line, the buttons, the OSR2 row, the readout
_OSR2_H = 16   # the OSR2 read-out row's height


def hud_xy() -> tuple[int, int]:
    """Where the panel goes: the window's top-left corner, the same place the
    satellites put theirs."""
    return _MARGIN, _MARGIN


@dataclass(frozen=True)
class ConsoleHud:
    """Everything on the primary console: the top line, the room's controls, and
    — while Genau is driving — the drive readout.

    *modes* is drawn only where it applies (nau/hybrid); *console* is what Fun
    Time published; *drive* is the live readout, present only while a waveform is
    driving the device.
    """

    modes: ModeHud = field(default_factory=ModeHud)
    console: ConsoleModel = field(default_factory=ConsoleModel)
    drive: DriveHud | None = None


class ConsolePainter:
    """Paints the primary console, and only when something on it has moved.

    A player redraws its overlays every frame at 60 fps and Pillow is nowhere
    near cheap enough for that, so the bitmap is kept until the panel's contents
    change.  The button rects from the last painting are kept beside it — the
    console's own and the drive readout's arrows — so what is clickable is exactly
    what was drawn.
    """

    def __init__(self) -> None:
        self._body = load_font(_SIZE_BODY)
        self._tiny = load_font(_SIZE_TINY)
        self._glyph = load_font(_SIZE_BODY, SYMBOL_FONT)
        self._drive = DriveSection()
        self._painted: tuple[ConsoleHud, tuple[int, int] | None] | None = None
        self._image: Image.Image | None = None
        self._bgra: np.ndarray | None = None
        self.buttons: list[tuple[Rect, Button]] = []

    def bgra(self, hud: ConsoleHud, *, hover: tuple[int, int] | None = None) -> np.ndarray:
        """*hud* as an mpv overlay bitmap — what Nau composites into its video."""
        if self._ensure(hud, hover) or self._bgra is None:
            self._bgra = to_bgra(self._image)
        return self._bgra

    def rgba(self, hud: ConsoleHud, *, hover: tuple[int, int] | None = None,
             ) -> tuple[bytes, tuple[int, int]]:
        """*hud* as ``(rgba_bytes, size)`` — what pygame takes, for Genau to blit
        into its own window in genau mode.  The size varies with the contents, so
        the caller sizes its blit from what comes back."""
        self._ensure(hud, hover)
        return self._image.tobytes(), self._image.size

    def _ensure(self, hud: ConsoleHud, hover: tuple[int, int] | None) -> bool:
        """Repaint if *hud*/*hover* moved; report whether it did (so a cached
        bitmap can be reused).  The panel is redrawn a few times a minute at most
        — Pillow is too slow to run every frame — so the image is kept until it
        changes."""
        if (hud, hover) == self._painted and self._image is not None:
            return False
        self._painted, self._image = (hud, hover), self._paint(hud, hover)
        return True

    def command_at(self, mx: int, my: int) -> str:
        """The command a press at *window* point ``(mx, my)`` posts, "" over none."""
        return hit_test(self.buttons, *self._local(mx, my))

    def hover_at(self, mx: int, my: int) -> tuple[int, int] | None:
        """Where to name the button under *window* point ``(mx, my)``, else None."""
        local = self._local(mx, my)
        return local if tooltip_at(self.buttons, *local) else None

    @staticmethod
    def _local(mx: int, my: int) -> tuple[int, int]:
        """A window point in the panel's own coordinates."""
        left, top = hud_xy()
        return mx - left, my - top

    def _paint(self, hud: ConsoleHud, hover: tuple[int, int] | None = None) -> "Image.Image":
        rows = console_rows(hud.console)
        line = hud.modes.line
        drive_w, drive_h = DriveSection.SIZE if hud.drive is not None else (0, 0)
        body_ascent, body_descent = self._body.getmetrics()
        top_h = body_ascent + body_descent

        width = 2 * _PAD + max(
            row_width(rows), drive_w, self._osr2_width(hud.console),
            DOT + DOT_GAP + text_width(self._body, line),
        )
        height = (
            2 * _PAD + top_h + _ROW_GAP + rows_height(rows)
            + _ROW_GAP + _OSR2_H
        )
        if hud.drive is not None:
            height += _ROW_GAP + drive_h

        panel = HudPanel(width, height)
        draw = panel.draw

        # Top line: the dot, then Nau's mode line — one line, tight to the top so
        # the corner does not carry the empty band it used to.
        y = _PAD
        # White while a bare, player-less command lands here, the palette's grey
        # otherwise — the same dot, in the same corner and colour, as each
        # satellite's, so the primary reads as one of the family.
        dot_cy = y + top_h // 2
        draw.ellipse([_PAD, dot_cy - DOT // 2, _PAD + DOT, dot_cy - DOT // 2 + DOT],
                     fill=(*(WHITE if hud.console.active else TEXT_MUTED), 255))
        if line:
            draw.text((_PAD + DOT + DOT_GAP, y + body_ascent), line, font=self._body,
                      anchor="ls", fill=(*TEXT_PRIMARY, 255))
        y += top_h + _ROW_GAP

        self.buttons = place_rows(rows, x=_PAD, y=y)
        for rect, button in self.buttons:
            self._button(draw, rect, button)
        y += rows_height(rows) + _ROW_GAP

        self._osr2(draw, _PAD, y, hud.console)
        y += _OSR2_H

        if hud.drive is not None:
            y += _ROW_GAP
            self._drive.draw(draw, _PAD, y, hud.drive)
            # The readout draws its own arrows; the console only needs them as hit
            # targets, so they answer a press and name themselves on hover.
            for control in drive_controls(_PAD, y, hud.drive):
                self.buttons.append((
                    control.rect,
                    Button(control.action, "", _DRIVE_TIPS.get(control.action, ""),
                           dim=control.dim),
                ))

        if hover is not None:
            self._tooltip(draw, width, height, tooltip_at(self.buttons, *hover), hover)
        return panel.image

    def _osr2_width(self, model: ConsoleModel) -> int:
        state = _OSR2_LABELS.get(model.osr2, model.osr2)
        return (text_width(self._tiny, "OSR2") + 8
                + text_width(self._tiny, state) + 10
                + text_width(self._tiny, "Broker"))

    def _osr2(self, draw, x: int, y: int, model: ConsoleModel) -> None:
        """The OSR2 read-out: a muted label, a boxed state word, and the broker.

        A read-out, not a control — it says what has the device and whether the
        broker that talks to it is up.  Both are the primary's alone, which is why
        the broker light moved off the dashboard and onto this HUD.
        """
        draw.text((x, y + _OSR2_H / 2), "OSR2", font=self._tiny, anchor="lm",
                  fill=(*TEXT_MUTED, 255))
        state = _OSR2_LABELS.get(model.osr2, model.osr2)
        color = _OSR2_COLORS.get(model.osr2, TEXT_PRIMARY)
        box_x = x + text_width(self._tiny, "OSR2") + 8
        box_w = text_width(self._tiny, state) + 10
        draw.rounded_rectangle([box_x, y, box_x + box_w - 1, y + _OSR2_H - 1],
                               radius=3, outline=(*color, 255), width=1)
        draw.text((box_x + box_w / 2, y + _OSR2_H / 2), state, font=self._tiny,
                  anchor="mm", fill=(*color, 255))
        draw.text((box_x + box_w + 10, y + _OSR2_H / 2), "Broker", font=self._tiny,
                  anchor="lm", fill=(*(BLUE if model.broker else RED), 255))

    def _tooltip(self, draw, width: int, height: int, text: str, pos: tuple[int, int]) -> None:
        """A tooltip drawn inside the panel near the cursor — the HUD lives in the
        video, so there is no native one, and every glyph up here is cryptic."""
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
        """One control, in the one button shape this family's HUDs use: an outline
        when off, filled when on, faded when it cannot be pressed.

        A read-out — an item with nothing to post — is a bare value with no box."""
        x, y, w, h = rect
        if not button.action:
            draw.text((x + w / 2, y + h / 2), button.glyph, font=self._tiny, anchor="mm",
                      fill=(*TEXT_PRIMARY, 255))
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


def with_playback_speed(console: ConsoleModel, speed: float) -> ConsoleModel:
    """*console* with the drawing player's own video rate folded in — Nau knows
    its rate, Fun Time does not publish it, so it is added at draw time."""
    return replace(console, playback_speed=speed)
