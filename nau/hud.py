"""The main console — the HUD the player on the main slot draws.

Fun Time's dashboard used to draw a schematic of the two monitors and hang the
main player's controls off it.  The main player draws them itself now, and the
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
from genau.drive_hud import DriveHud, DriveSection, DriveTrack, track_command
from genau.drive_hud import controls as drive_controls
from genau.drive_hud import tracks as drive_tracks
from player_core.hud_panel import (
    BG_PRIMARY,
    BLUE,
    GREEN,
    PINK,
    RED,
    TEXT_MUTED,
    TEXT_PRIMARY,
    WHITE,
    HudPanel,
    draw_glyph,
    draw_icon,
    draw_tooltip,
    load_font,
    text_width,
    to_bgra,
)
from player_core.hud_status import SEPARATOR, status_line

from .console import (
    BROKER_ICON,
    BUTTON,
    FMODE_ICON,
    GAP,
    WAVE_ICON,
    Button,
    ConsoleModel,
    Rect,
    console_rows,
    hit_test,
    nau_displays,
    osr2_row,
    place_rows,
    row_width,
    rows_height,
    tooltip_at,
)
from .library import FULL, SHORTS

# The glyphs the console's buttons are drawn with come from Segoe UI Symbol;
# Segoe UI Bold has none of them and Pillow draws tofu rather than falling back.
SYMBOL_FONT = "seguisym.ttf"

# What the length modes are called on screen.  The library names them for what it
# filters on; the HUD names them for what the user asked for.
#
# MIXED is deliberately absent: it applies no length filter at all, so it narrows
# nothing and there is nothing to report — the same silence a satellite keeps where
# its act filter would go when it has none.  It could not say much anyway now that
# the library holds three kinds of thing rather than two: "a mix" names none of
# them, where "Shorts" and "Full length" each name what they kept.
_LENGTH_LABELS = {FULL: "Full length", SHORTS: "Shorts"}

# The two controls that wear an app mark rather than a glyph, and which mark:
# the broker's "B" and F-mode's "F", each the pink five-by-five letter its .ico
# carries (:data:`player_core.hud_panel.ICON_GRIDS`).  Keyed by the marker the
# console puts on the button, the way the waveform's is.
_APP_MARKS = {BROKER_ICON: "B", FMODE_ICON: "F"}

# A compilation is titled for a shelf: "various - Ultimate Example Studio Alpha
# Collection - Volume 6 (v1)".  Everything up to the last dash is the series and
# the trailing "(v1)" the archivist's revision, leaving the volume as the part
# that says which one you are inside.
_REVISION = re.compile(r"\s*\(v\d+\)$")

# What the OSR2 line says by what is driving the device, and the color it says
# it in — green when a funscript is driving, blue when Genau is, muted when
# nothing is, and the device's own pink when it is running itself in auto.
OSR2_GENAU = "genau"  # the one state in which the drive readout can be pressed
_OSR2_LABELS = {
    "off": "Off", "auto": "Auto", "funscript": "FunScript",
    OSR2_GENAU: "Genau", "idle": "Idle",
}
_OSR2_COLORS = {
    "funscript": GREEN, "genau": BLUE, "auto": PINK,
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

    *video* is the name of the clip on screen, drawn as the muted line beneath the
    status; it used to live in a chip of its own below the console, and now it
    heads the console instead.  The rest is what the status line is built from:
    *length_mode* is the library's filter, empty when there is no library behind
    the playlist; *compilation* is the volume holding the playlist, with
    *position*/*total* placing the current video in it; *f_mode* is Fun Time's
    filter over whichever of those runs.  All empty in genau mode, where there is
    no Nau playlist to describe and the line is the lock and Genau's own pace —
    see :attr:`ConsoleHud.status_line`, which is where these are put in order,
    since the lock they are said beside is the console's rather than Nau's.
    """

    video: str = ""
    length_mode: str = ""
    compilation: str = ""
    position: int = 0
    total: int = 0
    f_mode: bool = False


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
    """Everything on the main console: the top line, the room's controls, and
    — while Genau is driving — the drive readout.

    *modes* is drawn only where it applies (nau/hybrid); *console* is what Fun
    Time published; *drive* is the live readout, present only while a waveform is
    driving the device.
    """

    modes: ModeHud = field(default_factory=ModeHud)
    console: ConsoleModel = field(default_factory=ConsoleModel)
    drive: DriveHud | None = None

    @property
    def advance_interval(self) -> int:
        """How long an unlocked Genau leaves each clip up.

        Genau owns the pace, so it rides its own drive readout rather than the
        console panel Fun Time publishes — and is read back off the readout
        wherever the console needs it, which is both the auto-advance button and
        the status line.
        """
        if self.drive is not None:
            return self.drive.advance_interval
        return self.console.advance_interval

    @property
    def status_line(self) -> str:
        """The top line's text — everything selecting what is on the main slot, in
        the order each satellite's HUD says the same things.

        This player's words in the slots
        :func:`player_core.hud_status.status_line` lays out, which is where the
        grammar and the shared states' wording live — the satellites say the same
        sentence, and a reader glancing between two screens is reading one sentence
        in two places.

        What fills the slots is the main player's own.  The compilation is its playing
        set — a fixed run it plays through rather than the browse it came from.
        The order slot is empty under Nau, which has no Latest/Shuffle to report,
        and carries Genau's advance pace under Genau, whose whole browse order is
        how long it leaves a clip up.  The length mode is the filter, and "Mixed"
        prints nothing there: it is every length there is, so it narrows nothing —
        exactly as a satellite prints nothing where its act filter would go when it
        has none.
        """
        compilation = (
            f"{compilation_label(self.modes.compilation)}"
            f"{SEPARATOR}{self.modes.position}/{self.modes.total}"
        ) if self.modes.compilation else ""
        # Only while Genau is the one showing and is not holding: hybrid draws the
        # drive readout too, but an unlocked Nau plays through its playlist rather
        # than on a timer, so seconds there would describe the wrong player — and a
        # held clip has no pace at all, since nothing is going to move it on.
        pace = (f"{self.advance_interval}s"
                if (not self.console.locked and self.advance_interval
                    and not nau_displays(self.console.mode))
                else "")
        return status_line(
            playing_set=compilation,
            locked=self.console.locked,
            order=pace,
            f_mode=self.modes.f_mode,
            filter_label=_LENGTH_LABELS.get(self.modes.length_mode, ""),
        )


class ConsolePainter:
    """Paints the main console, and only when something on it has moved.

    A player redraws its overlays every frame at 60 fps and Pillow is nowhere
    near cheap enough for that, so the bitmap is kept until the panel's contents
    change.  The button rects from the last painting are kept beside it — the
    console's own and the drive readout's arrows — so what is clickable is exactly
    what was drawn, and the readout's own bands with them, so what is draggable is
    too.
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
        self.tracks: list[DriveTrack] = []
        # Which band a press took hold of, and what it last asked for, so a drag
        # keeps setting the one it started on and only speaks when the value moves.
        self._held: DriveTrack | None = None
        self._asked = ""

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

    def press_at(self, mx: int, my: int) -> str:
        """The command a press at *window* point ``(mx, my)`` posts, "" over none.

        A press inside one of the drive readout's bands takes hold of it as well
        as posting: :meth:`drag_to` then goes on setting that level as the pointer
        moves, so a bar can be dragged and not only clicked.  Anything already
        held is let go first, so a press on an ordinary button never leaves a band
        latched behind it.
        """
        self.release()
        px, py = self._local(mx, my)
        return hit_test(self.buttons, px, py) or self._grab(px, py)

    @property
    def holding(self) -> bool:
        """Whether a press took hold of one of the readout's bands and has not let
        go — so the player knows a drag belongs here rather than to whatever else
        it would have offered the pointer."""
        return self._held is not None

    def drag_to(self, mx: int, my: int) -> str:
        """The command the pointer posts while a band is held.

        "" while none is, and "" while the level under the pointer is the one
        already asked for — a drag along a bar fires per mouse motion, and every
        one of those that says nothing new is a line in the command file for Fun
        Time to route to a value Genau is already on.
        """
        if self._held is None:
            return ""
        command = track_command(self._held, *self._local(mx, my))
        if command == self._asked:
            return ""
        self._asked = command
        return command

    def release(self) -> None:
        """Let go of whichever band a press took hold of."""
        self._held, self._asked = None, ""

    def _grab(self, px: int, py: int) -> str:
        """Take hold of the band under panel point ``(px, py)`` and say what that
        press asks of it; "" over none, holding nothing.

        A dimmed band is passed over the way a dimmed button is: the readout is
        dimmed whole while a funscript has the device, and a press that could do
        nothing is not offered.
        """
        for track in self.tracks:
            x, y, w, h = track.rect
            if not track.dim and x <= px < x + w and y <= py < y + h:
                self._held = track
                self._asked = track_command(track, px, py)
                return self._asked
        return ""

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
        drive = hud.drive
        if drive is not None:
            console = replace(console, advance_interval=hud.advance_interval)
            # Genau cannot see the handoff, so whoever draws the console tells the
            # readout whether Genau has the device.  While a funscript does, every
            # control on it is greyed and answers no press — adjusting a stroke
            # Genau is not sending is what woke it against the funscript.
            drive = replace(drive, driving=console.osr2 == OSR2_GENAU)
        rows = console_rows(console)
        status = hud.status_line
        filename = hud.modes.video
        drive_w, drive_h = DriveSection.SIZE if drive is not None else (0, 0)
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
        if drive is not None:
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
        # satellite's, so the main player reads as one of the family.
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

        self.buttons, self.tracks = place_rows(rows, x=_PAD, y=y), []
        for rect, button in self.buttons:
            self._button(draw, rect, button)
        y += rows_height(rows) + _ROW_GAP

        self._osr2(draw, _PAD, y, console)
        y += _OSR2_H

        if drive is not None:
            y += _ROW_GAP
            self._drive.draw(draw, _PAD, y, drive)
            # The readout draws its own arrows; the console only needs them as hit
            # targets, so they answer a press and name themselves on hover.
            for control in drive_controls(_PAD, y, drive):
                self.buttons.append((
                    control.rect,
                    Button(control.action, "", _DRIVE_TIPS.get(control.action, ""),
                           dim=control.dim),
                ))
            # The bands are set by pressing in them rather than by posting a fixed
            # command, so they are their own targets (:meth:`_grab`) — but they
            # join the buttons as read-outs too, with no action to post, purely so
            # each one names what it sets when the cursor rests on it.  A bar that
            # can be dragged says so nowhere else on a HUD drawn into the video.
            self.tracks = drive_tracks(_PAD, y, drive)
            for track in self.tracks:
                self.buttons.append((track.rect, Button("", "", track.tooltip)))

        if hover is not None:
            tip = tooltip_at(self.buttons, *hover)
            if tip:
                draw_tooltip(draw, self._tiny, tip, hover, (width, height))
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

    def _button(self, draw, rect: Rect, button: Button) -> None:
        """One control, in the one button shape this family's HUDs use: an outline
        when off, filled when on, faded when it cannot be pressed.

        On is white, except where green applies: green across this family is kept
        for the favorites and the funscripts, so F-mode — which narrows the
        playlist to what has a funscript — lights green and a mode, cruise or auto
        advance does not.  Two controls wear an app mark instead of a glyph and
        keep its pink whatever the button is doing: F-mode's "F", and the broker's
        "B" on blue or red, the face it wore on the dashboard — the broker being
        the room's own service and not one of these controls at all.

        A read-out — an item with nothing to post — is bare text with no box, in
        the readout's own key/value colors: a muted word names the value beside
        it, which is bright."""
        x, y, w, h = rect
        if not button.action:
            ink = TEXT_MUTED if button.glyph.replace(" ", "").isalpha() else TEXT_PRIMARY
            draw.text((x + w / 2, y + h / 2), button.glyph, font=self._tiny, anchor="mm",
                      fill=(*ink, 255))
            return
        broker = button.glyph == BROKER_ICON
        lit = GREEN if button.favorite else WHITE
        fill = lit if button.lit else RED if button.warn else BLUE if button.hold else None
        if broker:
            fill = BLUE if button.lit else RED
        edge = TEXT_MUTED if button.dim else (fill or TEXT_MUTED)
        draw.rounded_rectangle([x, y, x + w - 1, y + h - 1], radius=3,
                               fill=(*fill, 255) if fill else None,
                               outline=(*edge, 255), width=1)
        # The mark stays white over a colored fill and reverses out of a white
        # one, so a control that changes state changes only what is behind its
        # mark — the way the Dash's mic keeps its white glyph while the panel
        # under it goes blue.  A record button whose circle went dark while it
        # recorded read as a different button, not as the same one recording.
        ink = (BG_PRIMARY if fill == WHITE else WHITE if fill
               else TEXT_MUTED if button.dim else TEXT_PRIMARY)
        if button.glyph in _APP_MARKS:
            draw_icon(draw, rect, _APP_MARKS[button.glyph])
        elif button.glyph == WAVE_ICON:
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
