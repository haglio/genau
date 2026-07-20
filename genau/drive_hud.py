"""Genau's drive readout — the stroke it is sending the device, drawn.

This is the panel that used to be hand-drawn with ``pygame.draw`` calls straight
into Genau's own layered window: a black rectangle of ad-hoc greys and blues,
Consolas at one size, two bare numbers and a two-letter flag.  Every other HUD in
this family had already moved onto :mod:`player_core.hud_panel` — the rounded
translucent slab, the Segoe face, the shared palette — and this was the last one
that had not.

Now the readout carries its own controls: the speed bar has a −/+ at its ends,
the amplitude bar a ▲/▼ at its ends, and the centre a ▲/▼ in the gutter beside
its line.  So the numbers and the ways to change them are the same object, drawn
once, whether the primary console is being drawn by Nau (over its video, in
Hybrid) or by Genau (into its own window, in Genau mode).

It is a Pillow block, not a panel: it hosts inside the console's slab rather than
carrying one of its own, so the console is one HUD and not two stacked on it.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from player_core.file_channel import publish_whole
from player_core.hud_panel import (
    AMBER,
    BG_PRIMARY,
    BLUE,
    GREEN,
    TEXT_MUTED,
    TEXT_PRIMARY,
    load_font,
    text_width,
)

Rect = tuple[int, int, int, int]  # (x, y, w, h)

# The block, sized for full labels and the integrated controls.
SECTION_W, SECTION_H = 250, 150

_SIZE_TINY = 8
_LABEL_H = 14        # a "key value" line
_BAR_H = 12          # the speed track's thickness
_CTRL = 14           # an integrated control button (square)
_GAP = 6
_AMP_W = 18          # the amplitude bar's width
_GUTTER = _CTRL      # the left column the centre controls sit in
_TRACK = (56, 56, 62)  # the unfilled part of a bar — a shade off the slab

# Position is a T-Code stroke position, 0 at the bottom of the range.
POSITION_MAX = 9999

_SHAPE_LABELS = {"rounded_square": "Square"}

_KEY_GAP = 6  # between a key and the value it names


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


def shape_label(shape: str) -> str:
    """The waveform's name as the panel prints it.

    The old panel drew the trace and never said which shape it was, so after
    cycling you could only infer it from the curve.  ``rounded_square`` is the
    one whose internal name reads badly spelled out; the rest title-case.
    """
    if shape in _SHAPE_LABELS:
        return _SHAPE_LABELS[shape]
    return " ".join(word.capitalize() for word in shape.split("_"))


@dataclass(frozen=True)
class DriveHud:
    """What Genau is driving the device with, ready to be drawn.

    ``waveform`` is the stroke sampled left to right as 0-1 positions — the same
    samples the device is being sent, so the trace is the motion rather than a
    picture of it.  The ``*_at_max`` / ``*_at_min`` flags say which controls have
    run out of range, so the readout can grey the arrow that would do nothing.
    Frozen and compared whole, so the painter can skip a redraw while nothing has
    moved.
    """

    speed: int = 0
    amplitude: int = 0
    center: int = 0
    shape: str = "sine"
    position: int = 0
    # Cruise varies the stroke; auto advance moves on to the next clip.  Two
    # switches, armed separately, so the panel has to be able to say either.
    cruise: bool = False
    auto_advance: bool = False
    # A held clip: auto advance is still armed, but sitting still.
    clip_locked: bool = False
    # Seconds between auto-advances, so the readout can say the pace it is set to;
    # 0 means the jittered default, which has no single number to show.
    advance_interval: int = 0
    playing: bool = False
    spd_at_max: bool = False
    spd_at_min: bool = False
    amp_at_max: bool = False
    amp_at_min: bool = False
    ctr_at_max: bool = False
    ctr_at_min: bool = False
    waveform: tuple[float, ...] = ()


# Each integrated control: its command, the flag on the DriveHud that greys it
# out at its limit, and where it sits.  One table, so the drawing and the
# hit-testing place every arrow from the same source.
_UP, _DOWN = "up", "down"


@dataclass(frozen=True)
class DriveControl:
    rect: Rect
    action: str
    glyph: str
    dim: bool


@dataclass(frozen=True)
class _Geometry:
    """Every rect the readout draws or hit-tests, placed once from the block's
    top-left corner, so the trace and the arrow over it cannot drift apart."""

    speed_bar: Rect
    speed_down: Rect
    speed_up: Rect
    wave: Rect
    amp_bar: Rect
    amp_up: Rect
    amp_down: Rect
    center_up: Rect
    center_down: Rect
    speed_label_x: int
    center_label_x: int
    label_y: int
    right: int
    foot_y: int


def _geometry(x: int, y: int, center_frac: float) -> _Geometry:
    right = x + SECTION_W
    bottom = y + SECTION_H
    content_x = x + _GUTTER + _GAP
    amp_x = right - _AMP_W
    speed_right = amp_x - _GAP

    label_y = y
    bar_row_y = label_y + _LABEL_H
    speed_down = (content_x, bar_row_y, _CTRL, _CTRL)
    speed_up = (speed_right - _CTRL, bar_row_y, _CTRL, _CTRL)
    bar_x = content_x + _CTRL + 4
    speed_bar = (bar_x, bar_row_y + (_CTRL - _BAR_H) // 2,
                 (speed_right - _CTRL - 4) - bar_x, _BAR_H)

    wave_top = bar_row_y + _CTRL + _GAP
    foot_y = bottom - _LABEL_H
    wave_bottom = foot_y - _GAP
    wave = (content_x, wave_top, speed_right - content_x, wave_bottom - wave_top)

    amp_up = (amp_x, wave_top, _AMP_W, _CTRL)
    amp_down = (amp_x, wave_bottom - _CTRL, _AMP_W, _CTRL)
    amp_bar = (amp_x, wave_top + _CTRL + 2, _AMP_W,
               (wave_bottom - _CTRL - 2) - (wave_top + _CTRL + 2))

    center_y = wave_top + round((1 - center_frac) * (wave[3] - 1))
    center_up = (x, center_y - _CTRL - 1, _GUTTER, _CTRL)
    center_down = (x, center_y + 1, _GUTTER, _CTRL)

    return _Geometry(
        speed_bar=speed_bar, speed_down=speed_down, speed_up=speed_up,
        wave=wave, amp_bar=amp_bar, amp_up=amp_up, amp_down=amp_down,
        center_up=center_up, center_down=center_down,
        speed_label_x=content_x, center_label_x=wave[0] + wave[2] // 2,
        label_y=label_y, right=right, foot_y=foot_y,
    )


def controls(x: int, y: int, hud: DriveHud) -> list[DriveControl]:
    """The readout's integrated arrows at ``(x, y)`` — speed −/+, amplitude ▲/▼,
    centre ▲/▼ — each carrying the command it posts and whether it is greyed out
    at the end of its range.  The console adds these to its hit targets, so a
    press on the trace's controls posts exactly what is drawn there."""
    g = _geometry(x, y, _fraction(hud.center))
    return [
        DriveControl(g.speed_down, "genau_speed_down", "−", hud.spd_at_min),
        DriveControl(g.speed_up, "genau_speed_up", "+", hud.spd_at_max),
        DriveControl(g.amp_up, "genau_amplitude_up", "▲", hud.amp_at_max),
        DriveControl(g.amp_down, "genau_amplitude_down", "▼", hud.amp_at_min),
        DriveControl(g.center_up, "genau_center_up", "▲", hud.ctr_at_max),
        DriveControl(g.center_down, "genau_center_down", "▼", hud.ctr_at_min),
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

        # The three values across the top — full words now, room for them: speed
        # over its bar, centre over the trace it marks, amplitude over its column.
        self._value(draw, g.label_y, "Speed", str(hud.speed), left=g.speed_label_x)
        self._value(draw, g.label_y, "Center", str(hud.center), center=g.center_label_x)
        self._value(draw, g.label_y, "Amp", str(hud.amplitude), right=g.right)

        self._bar(draw, g.speed_bar, fill=_fraction(hud.speed), color=GREEN)
        self._wave(draw, g.wave, hud)
        self._amp_bar(draw, g.amp_bar, hud)
        for control in controls(x, y, hud):
            self._control(draw, control)

        # The shape by name, and whichever hands-free switches are armed beside it.
        draw.text((x, g.foot_y + _LABEL_H / 2), shape_label(hud.shape), font=self._tiny,
                  anchor="lm", fill=(*TEXT_MUTED, 255))
        edge = g.right
        for label, color in self._flags(hud):
            draw.text((edge, g.foot_y + _LABEL_H / 2), label, font=self._tiny,
                      anchor="rm", fill=(*color, 255))
            edge -= text_width(self._tiny, label) + _GAP

    def _control(self, draw, control: DriveControl) -> None:
        """One integrated arrow: an outline box with its glyph, greyed at a limit."""
        x, y, w, h = control.rect
        ink = TEXT_MUTED if control.dim else TEXT_PRIMARY
        draw.rounded_rectangle([x, y, x + w - 1, y + h - 1], radius=3,
                               outline=(*ink, 255), width=1)
        draw.text((x + w / 2, y + h / 2 - 1), control.glyph, font=self._glyph,
                  anchor="mm", fill=(*ink, 255))

    @staticmethod
    def _flags(hud: DriveHud) -> list[tuple[str, tuple[int, int, int]]]:
        """The armed switches, in the order they are printed from the right.

        A held clip recolours auto advance rather than adding a flag of its own:
        the hold only exists inside auto advance, so it is a state of that switch.
        """
        flags: list[tuple[str, tuple[int, int, int]]] = []
        if hud.cruise:
            flags.append(("Cruise", AMBER))
        if hud.auto_advance:
            label = f"Auto {hud.advance_interval}s" if hud.advance_interval else "Auto"
            flags.append((label, BLUE if hud.clip_locked else AMBER))
        return flags

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
        draw.rectangle([x, y, x + w - 1, y + h - 1], fill=(*_TRACK, 96),
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
_FLAGS = ("cruise", "auto_advance", "clip_locked", "playing",
          "spd_at_max", "spd_at_min", "amp_at_max", "amp_at_min",
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
