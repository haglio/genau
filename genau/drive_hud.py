"""Genau's drive readout — the stroke it is sending the device, drawn.

This is the panel that used to be hand-drawn with ``pygame.draw`` calls straight
into Genau's own layered window: a black rectangle of ad-hoc greys and blues,
Consolas at one size, two bare numbers and a two-letter flag.  Every other HUD in
this family had already moved onto :mod:`player_core.hud_panel` — the rounded
translucent slab, the Segoe face, the shared palette — and this was the last one
that had not.

Each axis is now one object: its controls, its bar and its number together.
Centre sits down the left — its number, then a −/+ pair beside the dotted line it
moves.  Amplitude sits down the right — a −/+ pair at the ends of its bar, then
its number.  Speed sits under the trace, out of the way of the other two, with
its own −/+ at the ends of its bar and its number beneath.

It is a Pillow block, not a panel: it hosts inside the console's slab rather than
carrying one of its own, so the console is one HUD and not two stacked on it.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from player_core.file_channel import publish_whole
from player_core.hud_panel import (
    AMBER,
    BLUE,
    GREEN,
    TEXT_MUTED,
    TEXT_PRIMARY,
    draw_glyph,
    load_font,
    text_width,
)

Rect = tuple[int, int, int, int]  # (x, y, w, h)

_SIZE_TINY = 8
_LABEL_H = 14        # a "key value" line
_BAR_H = 12          # the speed track's thickness
_CTRL = 14           # an integrated control button (square)
_GAP = 6
_AMP_W = 18          # the amplitude bar's width
_WAVE_H = 96         # the trace's own height
# The side labels stack their number under their word, so each column is only as
# wide as the wider of the two rather than as wide as both plus a gap.
_CTR_LABEL_W = 34    # room for "Center" down the left
_AMP_LABEL_W = 24    # room for "Amp" down the right
_WAVE_W = 120        # the trace, between the two axis columns
_TRACK = (56, 56, 62)  # the unfilled part of a bar — a shade off the slab

# The block: the trace's band, then the speed row and its number under it.
SECTION_W = _CTR_LABEL_W + _GAP + _CTRL + _GAP + _WAVE_W + _GAP + _AMP_W + _GAP + _AMP_LABEL_W
SECTION_H = _WAVE_H + _GAP + _CTRL + 2 + _LABEL_H

# Position is a T-Code stroke position, 0 at the bottom of the range.
POSITION_MAX = 9999

_KEY_GAP = 6  # between a key and the value it names

# One pair of marks for every axis: the triangles that used to move amplitude and
# centre said "up/down" where speed said "less/more", which read as two different
# kinds of control for three things that are the same kind.
_LESS, _MORE = "−", "+"


def label_pair_x(font, key: str, value: str, *,
                 left: int | None = None, right: int | None = None) -> tuple[int, int]:
    """Where a "key value" pair's two words start, placed as one unit.

    Measured together and positioned together, so a value can never be dropped
    onto its own key.  Give *left* to run the pair rightwards from there, or
    *right* to end it at that edge.
    """
    span = text_width(font, key) + _KEY_GAP + text_width(font, value)
    start = left if left is not None else (right or 0) - span
    return start, start + text_width(font, key) + _KEY_GAP


@dataclass(frozen=True)
class DriveHud:
    """What Genau is driving the device with, ready to be drawn.

    ``waveform`` is the stroke sampled left to right as 0-1 positions — the same
    samples the device is being sent, so the trace is the motion rather than a
    picture of it.  It stops moving on its own while Genau is not stroking (in
    Hybrid, whenever a funscript has the device), because the phase it is sampled
    from stops advancing.  The ``*_at_max`` / ``*_at_min`` flags say which
    controls have run out of range, so the readout can grey the mark that would
    do nothing.  Frozen and compared whole, so the painter can skip a redraw
    while nothing has moved.
    """

    speed: int = 0
    amplitude: int = 0
    center: int = 0
    shape: str = "sine"
    position: int = 0
    # Seconds between auto-advances.  Carried here because Fun Time does not know
    # it — Genau owns the pace — and the console's auto-advance button says it.
    advance_interval: int = 0
    # Whether Genau is the one driving the device.  Not published — Genau cannot
    # see the handoff; whoever draws the console knows it from the OSR2 state and
    # folds it in.  False greys every control here, because a stroke Genau is not
    # sending cannot be adjusted: pressing one during a funscript's turn is what
    # put two drivers on the device at once.
    driving: bool = True
    spd_at_max: bool = False
    spd_at_min: bool = False
    amp_at_max: bool = False
    amp_at_min: bool = False
    ctr_at_max: bool = False
    ctr_at_min: bool = False
    waveform: tuple[float, ...] = ()


@dataclass(frozen=True)
class DriveControl:
    rect: Rect
    action: str
    glyph: str
    dim: bool


@dataclass(frozen=True)
class _Geometry:
    """Every rect the readout draws or hit-tests, placed once from the block's
    top-left corner, so the trace and the mark over it cannot drift apart."""

    wave: Rect
    speed_bar: Rect
    speed_down: Rect
    speed_up: Rect
    amp_bar: Rect
    amp_up: Rect
    amp_down: Rect
    center_up: Rect
    center_down: Rect
    center_label_right: int
    amp_label_left: int
    axis_label_y: int
    speed_label_y: int
    speed_label_x: int


def _geometry(x: int, y: int, center_frac: float) -> _Geometry:
    ctr_ctrl_x = x + _CTR_LABEL_W + _GAP
    wave_x = ctr_ctrl_x + _CTRL + _GAP
    amp_x = wave_x + _WAVE_W + _GAP
    wave = (wave_x, y, _WAVE_W, _WAVE_H)
    wave_bottom = y + _WAVE_H

    amp_up = (amp_x, y, _AMP_W, _CTRL)
    amp_down = (amp_x, wave_bottom - _CTRL, _AMP_W, _CTRL)
    amp_bar = (amp_x, y + _CTRL + 2, _AMP_W, _WAVE_H - 2 * (_CTRL + 2))

    # The centre marks ride its dotted line, kept inside the trace's band so a
    # centre at either end cannot push one off the block.
    center_y = y + round((1 - center_frac) * (_WAVE_H - 1))
    up_y = min(max(y, center_y - _CTRL - 1), wave_bottom - 2 * _CTRL - 2)
    center_up = (ctr_ctrl_x, up_y, _CTRL, _CTRL)
    center_down = (ctr_ctrl_x, up_y + _CTRL + 2, _CTRL, _CTRL)

    speed_y = wave_bottom + _GAP
    speed_down = (wave_x, speed_y, _CTRL, _CTRL)
    speed_up = (amp_x + _AMP_W - _CTRL, speed_y, _CTRL, _CTRL)
    bar_x = wave_x + _CTRL + 4
    speed_bar = (bar_x, speed_y + (_CTRL - _BAR_H) // 2,
                 (amp_x + _AMP_W - _CTRL - 4) - bar_x, _BAR_H)

    return _Geometry(
        wave=wave, speed_bar=speed_bar, speed_down=speed_down, speed_up=speed_up,
        amp_bar=amp_bar, amp_up=amp_up, amp_down=amp_down,
        center_up=center_up, center_down=center_down,
        center_label_right=x + _CTR_LABEL_W,
        amp_label_left=amp_x + _AMP_W + _GAP,
        axis_label_y=y + (_WAVE_H - 2 * _LABEL_H) // 2,
        speed_label_y=speed_y + _CTRL + 2,
        speed_label_x=(wave_x + amp_x + _AMP_W) // 2,
    )


def controls(x: int, y: int, hud: DriveHud) -> list[DriveControl]:
    """The readout's own marks at ``(x, y)`` — a −/+ pair for each of speed,
    amplitude and centre — each carrying the command it posts and whether it is
    greyed out at the end of its range.  The console adds these to its hit
    targets, so a press on the trace's controls posts exactly what is drawn."""
    g = _geometry(x, y, _fraction(hud.center))
    idle = not hud.driving
    return [
        DriveControl(g.speed_down, "genau_speed_down", _LESS, idle or hud.spd_at_min),
        DriveControl(g.speed_up, "genau_speed_up", _MORE, idle or hud.spd_at_max),
        DriveControl(g.amp_up, "genau_amplitude_up", _MORE, idle or hud.amp_at_max),
        DriveControl(g.amp_down, "genau_amplitude_down", _LESS, idle or hud.amp_at_min),
        DriveControl(g.center_up, "genau_center_up", _MORE, idle or hud.ctr_at_max),
        DriveControl(g.center_down, "genau_center_down", _LESS, idle or hud.ctr_at_min),
    ]


class DriveSection:
    """The readout itself, drawn into whatever panel is hosting it."""

    SIZE = (SECTION_W, SECTION_H)

    def __init__(self) -> None:
        self._tiny = load_font(_SIZE_TINY)
        self._glyph = load_font(_LABEL_H - 3, "seguisym.ttf")

    def draw(self, draw, x: int, y: int, hud: DriveHud) -> None:
        """Paint the readout with its top-left corner at ``(x, y)``."""
        g = _geometry(x, y, _fraction(hud.center))

        self._wave(draw, g.wave, hud)
        self._amp_bar(draw, g.amp_bar, hud)
        self._bar(draw, g.speed_bar, fill=_fraction(hud.speed), color=GREEN)
        for control in controls(x, y, hud):
            self._control(draw, control)

        # Each number beside the controls that move it: centre out to the left,
        # amplitude out to the right, speed under its own row.  The two side
        # labels stack — word over number — so the columns cost half the width.
        self._stacked(draw, g.axis_label_y, "Center", str(hud.center),
                      right=g.center_label_right)
        self._stacked(draw, g.axis_label_y, "Amp", str(hud.amplitude),
                      left=g.amp_label_left)
        self._value(draw, g.speed_label_y, "Speed", str(hud.speed),
                    center=g.speed_label_x)

    def _control(self, draw, control: DriveControl) -> None:
        """One integrated mark: an outline box with its glyph, greyed at a limit."""
        x, y, w, h = control.rect
        ink = TEXT_MUTED if control.dim else TEXT_PRIMARY
        draw.rounded_rectangle([x, y, x + w - 1, y + h - 1], radius=3,
                               outline=(*ink, 255), width=1)
        draw_glyph(draw, x + w / 2, y + h / 2, control.glyph, self._glyph, (*ink, 255))

    def _stacked(self, draw, y: int, key: str, value: str, *,
                 left: int | None = None, right: int | None = None) -> None:
        """A muted word with its bright number under it, in one narrow column.

        The pair side by side cost the width of both plus a gap on each flank of
        the trace; stacked, each column is only as wide as the wider of the two.
        """
        for line_no, (text, ink) in enumerate(((key, TEXT_MUTED), (value, TEXT_PRIMARY))):
            x = left if left is not None else (right or 0) - text_width(self._tiny, text)
            draw.text((x, y + line_no * _LABEL_H + _LABEL_H / 2), text, font=self._tiny,
                      anchor="lm", fill=(*ink, 255))

    def _value(self, draw, y: int, key: str, value: str, *,
               left: int | None = None, right: int | None = None,
               center: int | None = None) -> None:
        """A muted key with its bright value, placed as one unit."""
        if center is not None:
            span = text_width(self._tiny, key) + _KEY_GAP + text_width(self._tiny, value)
            left = center - span // 2
        key_x, value_x = label_pair_x(self._tiny, key, value, left=left, right=right)
        draw.text((key_x, y + _LABEL_H / 2), key, font=self._tiny, anchor="lm",
                  fill=(*TEXT_MUTED, 255))
        draw.text((value_x, y + _LABEL_H / 2), value, font=self._tiny, anchor="lm",
                  fill=(*TEXT_PRIMARY, 255))

    @staticmethod
    def _bar(draw, rect: Rect, *, fill: float, color) -> None:
        x, y, w, h = rect
        draw.rectangle([x, y, x + w - 1, y + h - 1], fill=(*_TRACK, 255))
        filled = max(1, round(fill * w))
        draw.rectangle([x, y, x + filled - 1, y + h - 1], fill=(*color, 255))

    def _wave(self, draw, rect: Rect, hud: DriveHud) -> None:
        """The stroke drawn as a trace, with the centre marked across it and the
        device's live position marked down the left edge."""
        x, y, w, h = rect
        # Opaque, like every other panel on this HUD.  Half-transparent, the video
        # showed through the one place on the console you have to read a shape.
        draw.rectangle([x, y, x + w - 1, y + h - 1], fill=(*_TRACK, 255),
                       outline=(*TEXT_MUTED, 160), width=1)
        centre_y = y + round((1 - _fraction(hud.center)) * (h - 1))
        for dash in range(0, w, 6):
            draw.line([(x + dash, centre_y), (min(x + dash + 3, x + w - 1), centre_y)],
                      fill=(*AMBER, 150))
        points = hud.waveform
        if len(points) >= 2:
            draw.line(
                [(x + round(i / (len(points) - 1) * (w - 1)),
                  y + round((1 - value) * (h - 1)))
                 for i, value in enumerate(points)],
                fill=(*BLUE, 255), width=2, joint="curve",
            )
        dot_y = y + round((1 - hud.position / POSITION_MAX) * (h - 1))
        draw.ellipse([x - 3, dot_y - 3, x + 3, dot_y + 3], fill=(*TEXT_PRIMARY, 255))

    @staticmethod
    def _amp_bar(draw, rect: Rect, hud: DriveHud) -> None:
        """The stroke's extent as a bar: as tall as the amplitude, sitting where
        the centre puts it, so the pair reads as the range the device travels."""
        x, y, w, h = rect
        draw.rectangle([x, y, x + w - 1, y + h - 1], fill=(*_TRACK, 255))
        bar_h = max(2, round(_fraction(hud.amplitude) * h))
        top = y + round((1 - _fraction(hud.center)) * h - bar_h / 2)
        top = max(y, min(y + h - bar_h, top))
        draw.rectangle([x, top, x + w - 1, top + bar_h - 1], fill=(*BLUE, 255))


# --- publishing --------------------------------------------------------------
# In Hybrid the readout is drawn by Nau, inside its console, under the controls
# that move it — so Genau stops drawing and starts saying.  A file, like every
# other channel between these players: the reader polls per frame, and a torn or
# missing read simply means "keep the readout you have".

_SCALARS = ("speed", "amplitude", "center", "position", "advance_interval")
_FLAGS = ("spd_at_max", "spd_at_min", "amp_at_max", "amp_at_min",
          "ctr_at_max", "ctr_at_min")


def drive_text(hud: DriveHud) -> str:
    """*hud* as the line-per-field text :func:`read_drive` parses back."""
    lines = [f"{name}={getattr(hud, name)}" for name in _SCALARS]
    lines += [f"{name}={'1' if getattr(hud, name) else '0'}" for name in _FLAGS]
    lines.append(f"shape={hud.shape}")
    lines.append("waveform=" + ",".join(f"{value:.3f}" for value in hud.waveform))
    return "\n".join(lines) + "\n"


def publish_drive(path: Path, hud: DriveHud) -> bool:
    """Write the readout whole, so a player polling it never reads it half-drawn."""
    return publish_whole(path, drive_text(hud))


def read_drive(path: Path) -> DriveHud | None:
    """The published readout, or None when there is not a whole one to read.

    None means "keep what you have": the file is replaced while this polls it, and
    a lost race must not blank the readout for a frame.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    values = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    if not values.keys() >= {*_SCALARS, *_FLAGS, "shape"}:
        return None
    try:
        scalars = {name: int(values[name]) for name in _SCALARS}
    except ValueError:
        return None
    return DriveHud(
        **scalars,
        **{name: values[name].strip() == "1" for name in _FLAGS},
        shape=values["shape"].strip(),
        waveform=_waveform(values.get("waveform", "")),
    )


def _waveform(raw: str) -> tuple[float, ...]:
    try:
        return tuple(float(value) for value in raw.split(",") if value)
    except ValueError:
        return ()


def _fraction(percent: int) -> float:
    """A 0-100 control value as a 0-1 bar fill, clamped."""
    return max(0.0, min(1.0, percent / 100))
