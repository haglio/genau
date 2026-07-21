"""The primary console — the HUD the player on the primary slot draws.

Fun Time's dashboard used to draw a schematic of the two monitors and hang the
primary's controls off it.  The primary player draws them itself now, and the
same console is drawn whichever player holds the slot: Nau over its video in nau
and hybrid, Genau into its own window in genau.  So the mode switch and the drive
controls keep their places as you flip between modes — only the transport changes,
because it steps Nau's video in one and Genau's clips in the other.

Its top block is Nau's own answer to "what am I playing?" — the status line (the
length mode, or the compilation and your place in it) beside the active-player
dot, with the file on screen as a muted line under it, the same shape each
satellite's HUD leads with.  Both are empty in genau mode, where there is no Nau
playlist behind the screen.  The file name used to sit in a chip of its own below
the console; it belongs to this block now, so there is one HUD and not a panel
with a tag under it.  Everything else is the console the orchestrator publishes
(:mod:`nau.console`) plus, while Genau is driving, the drive readout
(:mod:`genau.drive_hud`) with its own controls.

The wording and shape are pure functions; the drawing goes onto the slab
:mod:`player_core.hud_panel` owns, the same slab the satellites' HUD is drawn on,
so every player says things the same way and from the same corner.
"""
from __future__ import annotations

import math
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
    draw_glyph,
    load_font,
    text_width,
    to_bgra,
)

from .console import (
    BUTTON,
    GAP,
    WAVE_ICON,
    Button,
    ConsoleModel,
    Rect,
    console_rows,
    hit_test,
    osr2_row,
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
    """Nau's own answer to "what am I playing?" — the console's top block.

    *video* is the name of the clip on screen, drawn beside the active dot; it
    used to live in a chip of its own below the console, and now it heads the
    console instead.  *length_mode* is the library's filter, empty when there is
    no library behind the playlist; *compilation* is the volume holding the
    playlist, with *position*/*total* placing the current video in it; *f_mode* is
    Fun Time's filter over whichever of those runs — together they are the muted
    subtitle under the name.  All empty in genau mode, where there is no Nau
    playlist to describe.
    """

    video: str = ""
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
_ROW_GAP = 4   # between the top block, the buttons, the OSR2 row, the readout
_SUBTITLE_GAP = 2  # between the status line and the file name under it
_OSR2_H = BUTTON      # the OSR2 line, sized to the controls sharing it
_OSR2_LABEL_GAP = 5   # "OSR2" sits right up against the pill it names …
_OSR2_GROUP_GAP = 16  # … and well clear of the two controls beside them


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
        # The pace auto advance is set to is Genau's, not Fun Time's, so it comes
        # up on the readout and is folded in here for the control that shows it.
        console = hud.console
        if hud.drive is not None:
            console = replace(console, advance_interval=hud.drive.advance_interval)
        rows = console_rows(console)
        status = hud.modes.line
        filename = hud.modes.video
        drive_w, drive_h = DriveSection.SIZE if hud.drive is not None else (0, 0)
        body_ascent, body_descent = self._body.getmetrics()
        top_h = body_ascent + body_descent
        tiny_h = sum(self._tiny.getmetrics())
        filename_h = (_SUBTITLE_GAP + tiny_h) if filename else 0
        text_x = _PAD + DOT + DOT_GAP

        width = 2 * _PAD + max(
            row_width(rows), drive_w, self._osr2_width(console),
            DOT + DOT_GAP + text_width(self._body, status),
            DOT + DOT_GAP + text_width(self._tiny, filename),
        )
        height = (
            2 * _PAD + top_h + filename_h + _ROW_GAP + rows_height(rows)
            + _ROW_GAP + _OSR2_H
        )
        if hud.drive is not None:
            height += _ROW_GAP + drive_h

        panel = HudPanel(width, height)
        draw = panel.draw

        # Top block: the active-player dot and the status line — what is selecting
        # this playlist — in the body face, with the file on screen as a muted line
        # under it.  Same shape as each satellite's HUD, which leads with its
        # status and not with a file name.  Both empty in genau mode.
        y = _PAD
        # White while a bare, player-less command lands here, the palette's grey
        # otherwise — the same dot, in the same corner and colour, as each
        # satellite's, so the primary reads as one of the family.
        dot_cy = y + top_h // 2
        draw.ellipse([_PAD, dot_cy - DOT // 2, _PAD + DOT, dot_cy - DOT // 2 + DOT],
                     fill=(*(WHITE if console.active else TEXT_MUTED), 255))
        if status:
            draw.text((text_x, y + body_ascent), status, font=self._body,
                      anchor="ls", fill=(*TEXT_PRIMARY, 255))
        y += top_h
        if filename:
            y += _SUBTITLE_GAP
            draw.text((text_x, y), filename, font=self._tiny, anchor="la",
                      fill=(*TEXT_MUTED, 255))
            y += tiny_h
        y += _ROW_GAP

        self.buttons = place_rows(rows, x=_PAD, y=y)
        for rect, button in self.buttons:
            self._button(draw, rect, button)
        y += rows_height(rows) + _ROW_GAP

        self._osr2(draw, _PAD, y, console)
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

    @staticmethod
    def _osr2_controls_width(controls: list[Button]) -> int:
        return sum(b.width for b in controls) + GAP * (len(controls) - 1)

    def _osr2_pill_width(self, model: ConsoleModel) -> int:
        return text_width(self._tiny, _OSR2_LABELS.get(model.osr2, model.osr2)) + 10

    def _osr2_width(self, model: ConsoleModel) -> int:
        return (self._osr2_controls_width(osr2_row(model)) + _OSR2_GROUP_GAP
                + text_width(self._tiny, "OSR2") + _OSR2_LABEL_GAP
                + self._osr2_pill_width(model))

    def _osr2(self, draw, x: int, y: int, model: ConsoleModel) -> None:
        """The device's own line: its two controls, then what has it.

        The broker and the takeover switch act on the OSR2 rather than on any
        player, so they share the OSR2's line and sit together at its head —
        placed by hand rather than through the row layout, which would read them
        as different families and open a gap between them.  The label then hugs
        its pill, well clear of the controls, so "OSR2 Genau" reads as one
        read-out instead of as a third button.
        """
        controls = osr2_row(model)
        run_x = x
        for button in controls:
            rect = (run_x, y, button.width, _OSR2_H)
            self._button(draw, rect, button)
            self.buttons.append((rect, button))
            run_x += button.width + GAP

        label_x = x + self._osr2_controls_width(controls) + _OSR2_GROUP_GAP
        draw.text((label_x, y + _OSR2_H / 2), "OSR2", font=self._tiny, anchor="lm",
                  fill=(*TEXT_MUTED, 255))
        state = _OSR2_LABELS.get(model.osr2, model.osr2)
        color = _OSR2_COLORS.get(model.osr2, TEXT_PRIMARY)
        pill_x = label_x + text_width(self._tiny, "OSR2") + _OSR2_LABEL_GAP
        pill_w = self._osr2_pill_width(model)
        draw.rounded_rectangle([pill_x, y, pill_x + pill_w - 1, y + _OSR2_H - 1],
                               radius=3, outline=(*color, 255), width=1)
        draw.text((pill_x + pill_w / 2, y + _OSR2_H / 2), state, font=self._tiny,
                  anchor="mm", fill=(*color, 255))

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

        A read-out — an item with nothing to post — is bare text with no box, in
        the readout's own key/value colours: a muted word names the value beside
        it, which is bright."""
        x, y, w, h = rect
        if not button.action:
            ink = TEXT_MUTED if button.glyph.isalpha() else TEXT_PRIMARY
            draw.text((x + w / 2, y + h / 2), button.glyph, font=self._tiny, anchor="mm",
                      fill=(*ink, 255))
            return
        fill = GREEN if button.lit else RED if button.warn else BLUE if button.hold else None
        edge = TEXT_MUTED if button.dim else (fill or TEXT_MUTED)
        draw.rounded_rectangle([x, y, x + w - 1, y + h - 1], radius=3,
                               fill=(*fill, 255) if fill else None,
                               outline=(*edge, 255), width=1)
        ink = BG_PRIMARY if fill else TEXT_MUTED if button.dim else TEXT_PRIMARY
        if button.glyph == WAVE_ICON:
            self._wave_icon(draw, rect, ink)
        elif len(button.glyph) == 1 and not button.glyph.isalnum():
            # A symbol needs the face that actually has it, and centring on its
            # own ink — the font's box would drop it toward the button's floor.
            draw_glyph(draw, x + w / 2, y + h / 2, button.glyph, self._glyph, (*ink, 255))
        else:
            draw.text((x + w / 2, y + h / 2), button.glyph, font=self._tiny,
                      anchor="mm", fill=(*ink, 255))

    @staticmethod
    def _wave_icon(draw, rect: Rect, ink) -> None:
        """The waveform control's face: a trace drawn to the button's own bounds.

        ∿ is a small mark sitting low in a tall box, so however it was centred it
        read as a smudge in the corner of the button rather than as an icon.  A
        curve drawn to fit says "waveform" at a glance and fills the square.
        """
        x, y, w, h = rect
        pad = 3
        x0, x1 = x + pad, x + w - pad - 1
        cy, amp = y + h / 2, (h - 2 * pad) / 2
        steps = 12
        draw.line(
            [(x0 + i * (x1 - x0) / steps, cy - amp * math.sin(2 * math.pi * i / steps))
             for i in range(steps + 1)],
            fill=(*ink, 255), width=2, joint="curve",
        )


def with_playback_speed(console: ConsoleModel, speed: float) -> ConsoleModel:
    """*console* with the drawing player's own video rate folded in — Nau knows
    its rate, Fun Time does not publish it, so it is added at draw time."""
    return replace(console, playback_speed=speed)
