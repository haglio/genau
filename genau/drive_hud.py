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

The marks step an axis; the axis itself is pressable.  Each bar and the trace is
already the picture of its own value, so a press in one asks for the value drawn
under the pointer and a held button goes on asking as it moves — see
:func:`tracks`.

It is a Pillow block, not a panel: it hosts inside the console's slab rather than
carrying one of its own, so the console is one HUD and not two stacked on it.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from player_core import drive_layout
from player_core.direct_control import POSITION_MAX  # noqa: F401
from player_core.drive_layout import (  # noqa: F401 — this module's public face
    AMPLITUDE,
    CENTER,
    SECTION_H,
    SECTION_W,
    SPEED,
    TRACE_ONLY_SIZE,
    TRACE_SAMPLES,
    DriveControl,
    DriveTrack,
    Rect,
    section_size,
    track_value,
)
from player_core.drive_layout import fraction as _fraction
from player_core.file_channel import publish_whole
from player_core.hud_panel import (
    BLUE,
    GREEN,
    TEXT_MUTED,
    TEXT_PRIMARY,
    WHITE,
    draw_glyph,
    load_font,
    text_width,
)

# What has the device, which is what the trace is a picture of.  Genau's own
# stroke and a video's funscript take turns in Hybrid; in Nau there is only ever
# the funscript, and with the OSR2 off or running itself nobody is sending
# anything at all.
DRIVEN_BY_GENAU = "genau"
DRIVEN_BY_FUNSCRIPT = "funscript"
DRIVEN_BY_NOTHING = "nothing"

# Green means the funscripts everywhere else on these HUDs — the favorites and
# the scripts — so it means one here too; blue is Genau's own stroke, the color
# its bars already wear.  Nothing driving is the same muted grey a dead control
# is drawn in, so the readout reads as one switched-off thing rather than as a
# live trace surrounded by dead furniture.
_TRACE_INK = {
    DRIVEN_BY_GENAU: BLUE,
    DRIVEN_BY_FUNSCRIPT: GREEN,
    DRIVEN_BY_NOTHING: TEXT_MUTED,
}


def trace_ink(driven: str):
    """The color a trace driven by *driven* is drawn in."""
    return _TRACE_INK[driven]

_SIZE_TINY = 8
_TRACK = (56, 56, 62)  # the unfilled part of a bar — a shade off the slab

_WAVE_W, _WAVE_H = TRACE_ONLY_SIZE
_LABEL_H = drive_layout.LABEL_H
_CTRL = drive_layout.CONTROL_SIZE
_GAP = drive_layout.GAP
_KEY_GAP = 6  # between a key and the value it names

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
    picture of it — spanning ``trace_seconds`` from now.  Whoever is driving
    supplies them: Genau's own stroke while it strokes, the funscript's shape
    while a funscript has the device (Nau samples that; Genau cannot see it), and
    the last shape drawn, held still, while nothing is being sent at all.  The
    ``*_at_max`` / ``*_at_min`` flags say which controls have run out of range,
    so the readout can dim the mark that would do nothing.  Frozen and compared
    whole, so the painter can skip a redraw while nothing has moved.
    """

    speed: int = 0
    amplitude: int = 0
    center: int = 0
    shape: str = "sine"
    position: int = 0
    # Seconds between auto-advances.  Carried here because Fun Time does not know
    # it — Genau owns the pace — and the console's auto-advance button says it.
    advance_interval: int = 0
    # What has the device.  Not published — Genau cannot see the handoff; whoever
    # draws the console knows it from the OSR2 state and folds it in.  Anything
    # but Genau dims every control here, because a stroke Genau is not sending
    # cannot be adjusted: pressing one during a funscript's turn is what put two
    # drivers on the device at once.
    driven: str = DRIVEN_BY_GENAU
    # How much time the trace spans, so a funscript sampled for it lines up with
    # the stroke it replaces.  Genau owns the number (it follows its own beats
    # per loop) and publishes it; a player with no Genau to ask keeps the default.
    trace_seconds: float = 12.0
    spd_at_max: bool = False
    spd_at_min: bool = False
    amp_at_max: bool = False
    amp_at_min: bool = False
    ctr_at_max: bool = False
    ctr_at_min: bool = False
    waveform: tuple[float, ...] = ()
    # Where the trace changes hands, as ``(sample index, who drives from there)``
    # pairs — empty meaning the whole line is ``driven``'s.  The span runs forward
    # from now, so a handoff that has not happened yet is *in* it: the last of a
    # funscript's action and the stroke waiting to take over are drawn as one line
    # that changes color at the join, which is the only way to see the seam
    # before it arrives rather than after it is over.
    segments: tuple[tuple[int, str], ...] = ()

    @property
    def driving(self) -> bool:
        """Whether Genau is the one driving — which is what its controls need."""
        return self.driven == DRIVEN_BY_GENAU

    @property
    def live(self) -> bool:
        """Whether anything at all is reaching the device.

        Nothing is, with the OSR2 off or running itself, and then the whole
        readout is a picture of a stroke nobody is making: it holds still and
        every part of it goes the muted grey of a dead control, the trace and the
        bars and the numbers alike.
        """
        return self.driven != DRIVEN_BY_NOTHING

    @property
    def runs(self) -> tuple[tuple[int, int, str], ...]:
        """``(start, end, driven)`` for each stretch of the trace, in order.

        Each run ends *on* the next one's first sample rather than before it, so
        consecutive runs share a point and the line is continuous across a change
        of hands instead of breaking at it.
        """
        marks = self.segments or ((0, self.driven),)
        ends = [start for start, _who in marks[1:]] + [len(self.waveform) - 1]
        return tuple((start, end, who) for (start, who), end in zip(marks, ends))


def controls(x: int, y: int, hud: DriveHud, *,
             trace_only: bool = False) -> list[DriveControl]:
    """The readout's marks at ``(x, y)``, read off *hud* — Genau's own view of
    :func:`player_core.drive_layout.controls`, which is where the rects and the
    dimming live.  The console adds these to its hit targets, so a press posts
    exactly what is drawn."""
    return drive_layout.controls(
        x, y, hud.center,
        drive_layout.Limits(
            spd_at_min=hud.spd_at_min, spd_at_max=hud.spd_at_max,
            amp_at_min=hud.amp_at_min, amp_at_max=hud.amp_at_max,
            ctr_at_min=hud.ctr_at_min, ctr_at_max=hud.ctr_at_max,
        ),
        dim=not hud.driving, prefix="genau_", trace_only=trace_only)


def tracks(x: int, y: int, hud: DriveHud, *,
           trace_only: bool = False) -> list[DriveTrack]:
    """The readout's bands at ``(x, y)``, read off *hud* — the three you press to
    set a level outright instead of walking to it with the marks."""
    return drive_layout.tracks(x, y, hud.center, dim=not hud.driving,
                         trace_only=trace_only)


def track_command(track: DriveTrack, px: int, py: int) -> str:
    """What a press at ``(px, py)`` on *track* posts — the numeric set command Fun
    Time already routes to Genau."""
    return f"genau_{track.axis}_{track_value(track, px, py)}"


class DriveSection:
    """The readout itself, drawn into whatever panel is hosting it."""

    def __init__(self) -> None:
        self._tiny = load_font(_SIZE_TINY)
        self._glyph = load_font(_LABEL_H - 3, "seguisym.ttf")

    def draw(self, draw, x: int, y: int, hud: DriveHud, *,
             trace_only: bool = False) -> None:
        """Paint the readout with its top-left corner at ``(x, y)``.

        *trace_only* draws the picture and nothing else, which is the whole
        readout in Nau: Genau is not behind that screen, so its levels have
        nothing to say and no control there could reach them.
        """
        if trace_only:
            self._wave(draw, (x, y, _WAVE_W, _WAVE_H), hud)
            return
        g = drive_layout.geometry(x, y, _fraction(hud.center))
        # Blue is Genau's own stroke — the trace, the amplitude bar and the speed
        # bar are all the same thing — and grey when nothing is reaching the
        # device: a live blue level beside a dead control says the level is doing
        # something.  Never the funscript's green: these are Genau's numbers, and
        # a script driving does not make them the script's.
        level_ink = BLUE if hud.live else TEXT_MUTED
        value_ink = TEXT_PRIMARY if hud.live else TEXT_MUTED

        self._wave(draw, g.wave, hud)
        self._amp_bar(draw, g.amp_bar, hud, color=level_ink)
        self._bar(draw, g.speed_bar, fill=_fraction(hud.speed), color=level_ink)
        for control in controls(x, y, hud):
            self._control(draw, control)

        # Each number beside the controls that move it: centre out to the left,
        # amplitude out to the right, speed under its own row.  The two side
        # labels stack — word over number — so the columns cost half the width.
        self._stacked(draw, g.axis_label_y, "Center", str(hud.center),
                      right=g.center_label_right, ink=value_ink)
        self._stacked(draw, g.axis_label_y, "Amp", str(hud.amplitude),
                      left=g.amp_label_left, ink=value_ink)
        self._value(draw, g.speed_label_y, "Speed", str(hud.speed),
                    center=g.speed_label_x, ink=value_ink)

    def _control(self, draw, control: DriveControl) -> None:
        """One integrated mark: an outline box with its glyph, dimmed at a limit."""
        x, y, w, h = control.rect
        ink = TEXT_MUTED if control.dim else TEXT_PRIMARY
        draw.rounded_rectangle([x, y, x + w - 1, y + h - 1], radius=3,
                               outline=(*ink, 255), width=1)
        draw_glyph(draw, x + w / 2, y + h / 2, control.glyph, self._glyph, (*ink, 255))

    def _stacked(self, draw, y: int, key: str, value: str, *,
                 left: int | None = None, right: int | None = None,
                 ink=TEXT_PRIMARY) -> None:
        """A muted word with its number under it, in one narrow column.

        The pair side by side cost the width of both plus a gap on each flank of
        the trace; stacked, each column is only as wide as the wider of the two.
        """
        for line_no, (text, text_ink) in enumerate(((key, TEXT_MUTED), (value, ink))):
            x = left if left is not None else (right or 0) - text_width(self._tiny, text)
            draw.text((x, y + line_no * _LABEL_H + _LABEL_H / 2), text, font=self._tiny,
                      anchor="lm", fill=(*text_ink, 255))

    def _value(self, draw, y: int, key: str, value: str, *,
               left: int | None = None, right: int | None = None,
               center: int | None = None, ink=TEXT_PRIMARY) -> None:
        """A muted key with its value, placed as one unit."""
        if center is not None:
            span = text_width(self._tiny, key) + _KEY_GAP + text_width(self._tiny, value)
            left = center - span // 2
        key_x, value_x = label_pair_x(self._tiny, key, value, left=left, right=right)
        draw.text((key_x, y + _LABEL_H / 2), key, font=self._tiny, anchor="lm",
                  fill=(*TEXT_MUTED, 255))
        draw.text((value_x, y + _LABEL_H / 2), value, font=self._tiny, anchor="lm",
                  fill=(*ink, 255))

    @staticmethod
    def _bar(draw, rect: Rect, *, fill: float, color) -> None:
        x, y, w, h = rect
        draw.rectangle([x, y, x + w - 1, y + h - 1], fill=(*_TRACK, 255))
        filled = max(1, round(fill * w))
        draw.rectangle([x, y, x + filled - 1, y + h - 1], fill=(*color, 255))

    def _wave(self, draw, rect: Rect, hud: DriveHud) -> None:
        """The stroke drawn as a trace, each stretch in the color of whoever
        drives it, with the centre marked across it and the device's position
        marked down the left edge.

        The centre's ruler is Genau's own idea and belongs to Genau's stroke, so
        a funscript's trace is drawn without it — a dotted line saying "the
        stroke swings about here" is a claim about a stroke nobody is making.
        """
        x, y, w, h = rect
        # Opaque, and the same grey whatever is behind it.  At part strength the
        # video showed through the border, so the one line that is supposed to be
        # a quiet edge read as a bright thick one over the picture and a thin dark
        # one over the letterbox — the same border looking like two.
        draw.rectangle([x, y, x + w - 1, y + h - 1], fill=(*_TRACK, 255),
                       outline=(*TEXT_MUTED, 255), width=1)
        # White, at the same part-strength it was drawn in before: the dotted line
        # is a ruler across the trace rather than a state of anything, and amber on
        # these HUDs is a warning's color, which this is not.
        if hud.driving:
            centre_y = y + round((1 - _fraction(hud.center)) * (h - 1))
            for dash in range(0, w, 6):
                draw.line([(x + dash, centre_y), (min(x + dash + 3, x + w - 1), centre_y)],
                          fill=(*WHITE, 150))
        points = hud.waveform
        if len(points) >= 2:
            def at(index: int) -> tuple[int, int]:
                return (x + round(index / (len(points) - 1) * (w - 1)),
                        y + round((1 - points[index]) * (h - 1)))

            for start, end, driven in hud.runs:
                if end > start:
                    draw.line([at(i) for i in range(start, end + 1)],
                              fill=(*trace_ink(driven), 255), width=2, joint="curve")
        # The device's own position, in the color of whoever is putting it there —
        # and held with the trace while nobody is, because a dot still bobbing in
        # a readout that has stopped is the last thing on it claiming to be live.
        dot_y = y + round((1 - hud.position / POSITION_MAX) * (h - 1))
        dot_ink = TEXT_PRIMARY if hud.live else TEXT_MUTED
        draw.ellipse([x - 3, dot_y - 3, x + 3, dot_y + 3], fill=(*dot_ink, 255))

    @staticmethod
    def _amp_bar(draw, rect: Rect, hud: DriveHud, *, color=BLUE) -> None:
        """The stroke's extent as a bar: as tall as the amplitude, sitting where
        the centre puts it, so the pair reads as the range the device travels."""
        x, y, w, h = rect
        draw.rectangle([x, y, x + w - 1, y + h - 1], fill=(*_TRACK, 255))
        bar_h = max(2, round(_fraction(hud.amplitude) * h))
        top = y + round((1 - _fraction(hud.center)) * h - bar_h / 2)
        top = max(y, min(y + h - bar_h, top))
        draw.rectangle([x, top, x + w - 1, top + bar_h - 1], fill=(*color, 255))


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
    # How much time the trace spans, so a funscript sampled to replace it covers
    # the same stretch: Genau's stroke and the script have to be the same picture
    # for a handoff between them to read as one line changing color.
    lines.append(f"trace_seconds={hud.trace_seconds:.3f}")
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
        trace_seconds=_seconds(values.get("trace_seconds", "")),
        waveform=_waveform(values.get("waveform", "")),
    )


def _seconds(raw: str) -> float:
    """The published trace span, or the default when an older publisher's file
    does not carry one."""
    try:
        return float(raw)
    except ValueError:
        return DriveHud.trace_seconds


def _waveform(raw: str) -> tuple[float, ...]:
    try:
        return tuple(float(value) for value in raw.split(",") if value)
    except ValueError:
        return ()
