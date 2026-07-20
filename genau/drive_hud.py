"""Genau's drive readout — the stroke it is sending the device, drawn.

This is the panel that used to be hand-drawn with ``pygame.draw`` calls straight
into Genau's own layered window: a black rectangle of ad-hoc greys and blues,
Consolas at one size, two bare numbers and a two-letter flag.  Every other HUD in
this family had already moved onto :mod:`player_core.hud_panel` — the rounded
translucent slab, the Segoe face, the shared palette — and this was the last one
that had not.

It is a Pillow painter rather than a pygame one because that is what both hosts
can take.  In Genau's own window the bitmap becomes an SDL texture; over Nau's
video it goes straight to mpv as an overlay, which is how the two players end up
showing one panel between them in Hybrid rather than two side by side.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image
from player_core.file_channel import publish_whole
from player_core.hud_panel import (
    AMBER,
    BLUE,
    GREEN,
    TEXT_MUTED,
    TEXT_PRIMARY,
    HudPanel,
    load_font,
    text_width,
    to_bgra,
)

_PAD = 10

# The readout's own block, sized for the labels the old panel did without: it
# printed a bare "100" beside the amplitude bar and nothing at all for the shape
# or the centre.  PANEL_SIZE is that block on a slab of its own, which is how
# Genau shows it; Nau draws the block inside its console instead.
SECTION_W, SECTION_H = 212, 112
PANEL_SIZE = (SECTION_W + 2 * _PAD, SECTION_H + 2 * _PAD)

_SIZE_BODY = 11
_SIZE_TINY = 8
_GAP = 6
_BAR_H = 10          # the speed track, above the wave
_AMP_W = 16          # the amplitude track, right of it
_LABEL_H = 13        # the key/value row over each track
_TRACK = (56, 56, 62)  # the unfilled part of a bar — a shade off the slab

# Position is a T-Code stroke position, 0 at the bottom of the range.
POSITION_MAX = 9999

_SHAPE_LABELS = {"rounded_square": "Square"}


_KEY_GAP = 6  # between a key and the value it names


def label_pair_x(font, key: str, value: str, *,
                 left: int | None = None, right: int | None = None) -> tuple[int, int]:
    """Where a "key value" pair's two words start, placed as one unit.

    Measured together and positioned together, so a value can never be dropped
    onto its own key — which is what happened when the amplitude's value was
    right-aligned to the narrow bar it labels while its key started to the left of
    that column.  Give *left* to run the pair rightwards from there, or *right* to
    end it at that edge; the pair is free to overhang whatever it labels.
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
    picture of it.  Frozen and compared whole, so the painter can skip a redraw
    while nothing has moved.
    """

    speed: int = 0
    amplitude: int = 0
    center: int = 0
    shape: str = "sine"
    position: int = 0
    cruise: bool = False
    playing: bool = False
    waveform: tuple[float, ...] = ()


class DriveSection:
    """The readout itself, drawn into whatever panel is hosting it.

    A block rather than a panel, because it has two hosts: Genau puts it on a slab
    of its own (:class:`DriveHudPainter` below), and Nau draws it inside its
    console, under the controls that change it.  Keeping it a block is what makes
    that second case one HUD rather than two stacked on each other.
    """

    SIZE = (SECTION_W, SECTION_H)

    def __init__(self) -> None:
        self._tiny = load_font(_SIZE_TINY)

    def draw(self, draw, x: int, y: int, hud: DriveHud) -> None:
        """Paint the readout with its top-left corner at ``(x, y)``."""
        right = x + SECTION_W

        # Speed, across the top, with the amplitude's own column reserved beside
        # it — the two tracks share a row of labels so the numbers line up.
        wave_right = right - _AMP_W - _GAP
        self._value(draw, y, "Speed", str(hud.speed), left=x)
        self._value(draw, y, "Amp", str(hud.amplitude), right=right)
        bar_y = y + _LABEL_H
        self._bar(draw, x, bar_y, wave_right - x, _BAR_H,
                  fill=_fraction(hud.speed), color=GREEN)

        # The wave itself, and the amplitude standing beside it: the bar's height
        # is the amplitude and its offset the centre, so the two together read as
        # "this much stroke, sitting here" without either number being needed.
        wave_y = bar_y + _BAR_H + _GAP
        wave_h = y + SECTION_H - _LABEL_H - _GAP - wave_y
        self._wave(draw, x, wave_y, wave_right - x, wave_h, hud)
        self._amp_bar(draw, wave_right + _GAP, wave_y, _AMP_W, wave_h, hud)

        # The shape by name, and cruise beside it when it is holding the speed.
        foot_y = y + SECTION_H - _LABEL_H
        draw.text((x, foot_y + _LABEL_H / 2), shape_label(hud.shape), font=self._tiny,
                  anchor="lm", fill=(*TEXT_MUTED, 255))
        if hud.cruise:
            draw.text((right, foot_y + _LABEL_H / 2), "Cruise", font=self._tiny,
                      anchor="rm", fill=(*AMBER, 255))

    def _value(self, draw, y: int, key: str, value: str,
               *, left: int | None = None, right: int | None = None) -> None:
        """A muted key with its bright value — the labelling the old panel had
        only for amplitude, and there as a bare number with nothing naming it."""
        key_x, value_x = label_pair_x(self._tiny, key, value, left=left, right=right)
        draw.text((key_x, y + _LABEL_H / 2), key, font=self._tiny, anchor="lm",
                  fill=(*TEXT_MUTED, 255))
        draw.text((value_x, y + _LABEL_H / 2), value, font=self._tiny, anchor="lm",
                  fill=(*TEXT_PRIMARY, 255))

    @staticmethod
    def _bar(draw, x: int, y: int, w: int, h: int, *, fill: float, color) -> None:
        draw.rectangle([x, y, x + w - 1, y + h - 1], fill=(*_TRACK, 255))
        filled = max(1, round(fill * w))
        draw.rectangle([x, y, x + filled - 1, y + h - 1], fill=(*color, 255))

    def _wave(self, draw, x: int, y: int, w: int, h: int, hud: DriveHud) -> None:
        """The stroke drawn as a trace, with the centre marked across it and the
        device's live position marked down the left edge."""
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
    def _amp_bar(draw, x: int, y: int, w: int, h: int, hud: DriveHud) -> None:
        """The stroke's extent as a bar beside the wave: as tall as the amplitude,
        sitting where the centre puts it, so the pair reads as the range the
        device is actually travelling."""
        draw.rectangle([x, y, x + w - 1, y + h - 1], fill=(*_TRACK, 255))
        bar_h = max(2, round(_fraction(hud.amplitude) * h))
        top = y + round((1 - _fraction(hud.center)) * h - bar_h / 2)
        top = max(y, min(y + h - bar_h, top))
        draw.rectangle([x, top, x + w - 1, top + bar_h - 1], fill=(*BLUE, 255))


class DriveHudPainter:
    """Genau's own panel: the readout on a slab of its own, repainted only when
    the drive state has moved.

    Genau redraws at its display rate and Pillow is nowhere near cheap enough for
    that, so the bitmap is kept until the state changes — which, while a stroke is
    running, is every tick, and while it is parked is never.  :meth:`rgba_bytes`
    is what pygame takes; :meth:`bgra` is what mpv's overlays take, so the same
    painting can go straight into a video.
    """

    def __init__(self) -> None:
        self._section = DriveSection()
        self._painted: DriveHud | None = None
        self._image: Image.Image | None = None
        self._bgra: np.ndarray | None = None

    def bgra(self, hud: DriveHud) -> np.ndarray:
        """The panel as an mpv overlay bitmap."""
        if self._repaint(hud) or self._bgra is None:
            self._bgra = to_bgra(self._image)
        return self._bgra

    def rgba_bytes(self, hud: DriveHud) -> bytes:
        """The panel as pygame's ``frombuffer(..., "RGBA")`` takes it."""
        self._repaint(hud)
        return self._image.tobytes()

    def _repaint(self, hud: DriveHud) -> bool:
        """Redraw if *hud* has moved; report whether it did."""
        if hud == self._painted and self._image is not None:
            return False
        panel = HudPanel(*PANEL_SIZE)
        self._section.draw(panel.draw, _PAD, _PAD, hud)
        self._painted, self._image = hud, panel.image
        return True


# --- publishing --------------------------------------------------------------
# In Hybrid the readout is drawn by Nau, inside its console, under the controls
# that move it — so Genau stops drawing and starts saying.  A file, like every
# other channel between these players: Nau polls it per frame, and a torn or
# missing read simply means "keep the readout you have".

_SCALARS = ("speed", "amplitude", "center", "position")
_FLAGS = ("cruise", "playing")


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
