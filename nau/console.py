"""The controls on the primary console, and where they sit.

Fun Time's dashboard used to draw a schematic of the two monitors with a little
box per player, and the primary player's box carried these controls.  The primary
player draws its own HUD now, so they live on it — and whichever player holds the
primary slot draws that HUD: Nau in nau and hybrid, Genau in genau mode.  The
console is the same in every mode, so the mode switch and the drive controls do
not move as you flip between them; only the transport changes, because prev/next
step Nau's video in nau/hybrid and Genau's clips in genau.

Kept free of Pillow, like ``satellite.hud`` is, so the rows, the geometry and the
hit-testing are testable without a font.  :mod:`nau.hud` paints them; the drive
readout's own arrows come from :mod:`genau.drive_hud`.

The action on each button is a Fun Time dashboard command verbatim, because that
is where a press goes: appended to the same command file the dashboard wrote, so
nothing new has to learn what these buttons mean, and Fun Time routes each to the
player the mode says owns it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

Rect = tuple[int, int, int, int]  # (x, y, w, h)

BUTTON = 18   # a square control; the wider ones are multiples plus the gaps
VALUE_W = 22  # a value read-out between a pair of buttons (the playback rate)
PLAYBACK_LABEL_W = 66  # the words naming that pair
GAP = 4       # between buttons along a row
ROW_GAP = 5   # between rows
GROUP_GAP = 12  # between groups of buttons that mean different things

_SHAPE_LABELS = {"rounded_square": "Square"}


def shape_label(shape: str) -> str:
    """The waveform's name, for the control that cycles it to say what it is on.

    ``rounded_square`` is the one whose internal name reads badly spelled out;
    the rest title-case.
    """
    if shape in _SHAPE_LABELS:
        return _SHAPE_LABELS[shape]
    return " ".join(word.capitalize() for word in shape.split("_"))


@dataclass(frozen=True)
class Button:
    """One item on the console: what it posts, what it looks like, how it is drawn.

    ``lit``, ``warn`` and ``hold`` are the live states — white for on, red for a
    live recording, blue for the loop that recording leaves running.  On is white
    rather than green because across this family green means the favorites and
    the funscripts; a mode being selected or cruise being armed is neither.
    ``favorite`` names the controls that *are* one of those, so their on-state
    keeps the green — F-mode is the only one so far.  ``dim`` is a control at the
    end of its range or with nothing to act on: drawn faded and left out of the
    hit targets, so a press that could do nothing is not offered.

    An empty ``action`` makes it a read-out: laid out in the row like anything
    else, drawn as a bare value with no box, and never a hit target.
    """

    action: str
    glyph: str
    tooltip: str
    width: int = BUTTON
    lit: bool = False
    warn: bool = False
    hold: bool = False
    dim: bool = False
    favorite: bool = False


@dataclass(frozen=True)
class ConsoleModel:
    """What Fun Time tells the primary player about its slot, so the console can
    draw it — none of which the player can see for itself.

    Everything here arrives published (``nau_console.json``) except
    ``playback_speed``, which is Nau's own and folded in by whoever is drawing.
    """

    mode: str = "nau"
    # The dot: whether a bare, player-less command ("next", "lock") lands on the
    # primary rather than on a satellite.
    active: bool = False
    # What is driving the OSR2 right now: off / auto / funscript / genau / idle.
    osr2: str = "off"
    # Whether the OSR2 broker service is up — its own concern, only the primary's.
    broker: bool = False
    # Where Nau's loop machine is: normal / recording (the record key is down and
    # the out point has not landed yet) / looping.  Nau publishes it in its status
    # file and Fun Time forwards it, because the console is drawn in genau mode too
    # — by a player that has no loop machine of its own to ask.
    record: str = "normal"
    # Whether Nau is holding the video on screen rather than letting it end.  On
    # is the primary's original behavior, so it is the default here too: a console
    # drawn before the first panel arrives must not show the lock off when it is
    # not.  Published the same way ``record`` is, and for the same reason — in
    # genau mode this console is drawn by a player with no such lock to ask.
    locked: bool = True
    # Whether the primary's own F-mode is on — its playlist narrowed to the videos
    # that have a funscript.  Nau is told the flag directly as well (its subtitle
    # says so), but the button lights off what Fun Time publishes, because the
    # flag is set from three places — this button, the F key, and a spoken phrase —
    # and only one of them is the player.
    f_mode: bool = False
    cruise: bool = False
    # The other hands-free switch: cruise varies the stroke, auto advance moves on
    # to the next clip.  A held clip is auto advance still armed but sitting still.
    auto_advance: bool = False
    clip_locked: bool = False
    shape: str = "sine"
    # Nau's video playback rate, shown while Nau is on screen.  Not published —
    # Nau knows its own rate and folds it in; Genau leaves it at 1.
    playback_speed: float = 1.0
    # Seconds between auto-advances.  Also not published — Genau owns the pace and
    # says it on the drive readout, which whoever draws the console folds in here.
    advance_interval: int = 0


def read_console(path: Path) -> ConsoleModel | None:
    """The console panel Fun Time published, or None when there is not a whole one.

    None means "keep the console you have": Fun Time replaces this file while the
    player polls it, so a lost race must not empty the panel for a frame.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or "mode" not in raw:
        return None
    return ConsoleModel(
        mode=str(raw.get("mode", "nau")),
        active=bool(raw.get("active", False)),
        f_mode=bool(raw.get("f_mode", False)),
        osr2=str(raw.get("osr2", "off") or "off"),
        broker=bool(raw.get("broker", False)),
        record=str(raw.get("record", "normal") or "normal"),
        locked=bool(raw.get("locked", True)),
        cruise=bool(raw.get("cruise", False)),
        auto_advance=bool(raw.get("auto_advance", False)),
        clip_locked=bool(raw.get("clip_locked", False)),
        shape=str(raw.get("shape", "sine") or "sine"),
    )


# The glyphs, all from Segoe UI Symbol — Segoe UI Bold has none of them, and
# Pillow draws tofu where Qt used to fall back silently.
_GLYPHS = {
    # The transport, in one family of marks: to the ends of the video with a bar,
    # ten seconds either way without one.  A bare −/+ said "less/more", which is
    # what the level controls say, not "back/forward through this".
    "prev": "⏮", "next": "⏭", "back": "⏪", "fwd": "⏩",
    "open": "📂", "record": "⏺", "save": "💾", "trash": "🗑",
    "lock": "🔒", "quarter": "¼", "minus": "−", "plus": "+",
}

# The waveform control draws a curve rather than a glyph: ∿ is a small mark low
# in a big box, so it read as a smudge in the corner of its button whatever the
# centring.  The painter recognises this marker and draws a trace that fills the
# button; nothing else on the console needs a bespoke icon.
WAVE_ICON = "\x00wave"

# The two controls that stand for an app rather than for an action, and so wear
# that app's mark: the pink five-by-five letter its .ico carries.  The broker's
# "B" sits on blue while the service is up and red while it is down; F-mode's "F"
# on the green the funscripts own.  The painter knows these markers the way it
# knows WAVE_ICON, so the console stays free of both colors and Pillow.
BROKER_ICON = "\x00broker"
FMODE_ICON = "\x00fmode"

_MODE_BUTTONS = (
    ("nau_activate", "Nau", "nau"),
    ("hybrid_activate", "Hybrid", "hybrid"),
    ("genau_activate", "Genau", "genau"),
)


def nau_displays(mode: str) -> bool:
    """Whether Nau's video is on the primary screen — nau and hybrid.

    The transport steps Nau's video then, and the nudge / open / clip / record
    that act on a video make sense; in genau mode the transport steps Genau's own
    clips instead and those video actions have nothing to act on.
    """
    return mode in ("nau", "hybrid")


def genau_drives(mode: str) -> bool:
    """Whether a waveform is driving the device — genau and hybrid.

    Only then do amplitude, centre, speed, cruise and the rest mean anything, so
    only then does the drive readout and its control row appear.
    """
    return mode in ("genau", "hybrid")


def _format_rate(rate: float) -> str:
    """A playback rate as a compact label: 1.0 -> '1×', 1.5 -> '1.5×'."""
    return f"{rate:g}×"


def console_rows(model: ConsoleModel) -> list[list[Button]]:
    """The console's buttons, row by row, for the mode Fun Time says it is in.

    The mode row leads, so it holds the same place in every mode.  Then the
    transport — Nau's video or Genau's clips — and, while Genau is driving, the
    hands-free control row (the drive readout's amplitude/centre/speed arrows are
    drawn on the readout itself, not here).
    """
    rows: list[list[Button]] = [
        [
            Button(action, label, f"{label} mode", width=BUTTON * 2 + GAP,
                   lit=model.mode == mode)
            for action, label, mode in _MODE_BUTTONS
        ],
    ]
    rows.append(_transport_row(model))
    if nau_displays(model.mode):
        rows.append(_playback_speed_row(model))
    if genau_drives(model.mode):
        rows.append(_control_row(model))
    return rows


def _transport_row(model: ConsoleModel) -> list[Button]:
    """Stepping and the actions on what is on screen.

    In nau/hybrid that is Nau's video — step it, nudge inside it, hold it against
    the end of the playlist's advance, browse for another, save a clip, record a
    loop.  In genau it is Genau's own clips — step them and mark one weird;
    nudge/hold/browse/clip/record have no video to act on.
    """
    if nau_displays(model.mode):
        return [
            # Ordered as the video runs: back to the last one, back ten, forward
            # ten, on to the next.
            Button("primary_prev", _GLYPHS["prev"], "Previous video"),
            Button("primary_nudge_prev", _GLYPHS["back"], "Back 10s"),
            Button("primary_nudge_next", _GLYPHS["fwd"], "Forward 10s"),
            Button("primary_next", _GLYPHS["next"], "Next video"),
            # What the end of the video does, so it belongs with the stepping:
            # locked (the primary's default) the video repeats and the two
            # buttons beside it are the only way off it; unlocked it plays out
            # into the next one and the playlist runs around.  The same padlock a
            # satellite's HUD carries, and lit the same way when it is on.
            Button("primary_lock", _GLYPHS["lock"],
                   "Locked — this video repeats; press to play on through the "
                   "playlist" if model.locked
                   else "Unlocked — plays on through the playlist; press to hold "
                        "this video",
                   lit=model.locked),
            # F-mode is per player now — Fun Time's dashboard used to carry one
            # switch for the room and every player carries its own instead.  Here
            # it narrows the playlist to the videos that have a funscript, so it
            # sits with the browser: both change what there is to step through,
            # rather than acting on the video on screen or on where it ends.
            Button("primary_fmode", FMODE_ICON,
                   "F-Mode — play only the videos that have a funscript",
                   lit=model.f_mode, favorite=True),
            Button("browse_library", _GLYPHS["open"], "Browse the library"),
            # Recording a loop and saving what it caught are one job in two
            # presses, so they sit together and apart from the browser.  The
            # record button carries the loop machine: red while the out point is
            # still being marked, blue once the loop is running — the two halves
            # of the gesture look different, so a press that is still open cannot
            # be mistaken for one that landed.
            Button("nau_record_tap", _GLYPHS["record"],
                   "Stop recording — mark the loop's out point"
                   if model.record == "recording" else
                   "Looping — press to drop the loop" if model.record == "looping"
                   else "Record loop",
                   warn=model.record == "recording",
                   hold=model.record == "looping"),
            Button("clipper_save", _GLYPHS["save"], "Save clip"),
        ]
    return [
        Button("genau_prev_clip", _GLYPHS["prev"], "Previous clip"),
        Button("genau_next_clip", _GLYPHS["next"], "Next clip"),
        Button("genau_weird_clip", _GLYPHS["trash"], "Mark weird — move it out"),
    ]


def _playback_speed_row(model: ConsoleModel) -> list[Button]:
    """Nau's video playback rate: slower, the rate itself, faster.

    Named, because "Speed" already means the *stroke* rate down on the drive
    readout and an unlabelled −/+ pair beside a number said neither.
    """
    return [
        Button("", "Playback speed", "", width=PLAYBACK_LABEL_W),
        Button("nau_speed_down", _GLYPHS["minus"], "Play the video slower"),
        Button("", _format_rate(model.playback_speed), "", width=VALUE_W),
        Button("nau_speed_up", _GLYPHS["plus"], "Play the video faster"),
    ]


def _advance_label(model: ConsoleModel) -> str:
    """The auto-advance control's face — with the pace it is set to, when it has
    one.  A bare arming jitters an 8-12s default, which has no number to show."""
    return f"aa {model.advance_interval}s" if model.advance_interval else "aa"


def _control_row(model: ConsoleModel) -> list[Button]:
    """The hands-free switches, the hold and the offset — everything Genau does
    that is not a level on the readout."""
    return [
        Button("genau_toggle_cruise", "cc",
               "Cruise control: vary the stroke hands-free", lit=model.cruise),
        # Armed is armed, whether or not a clip is being held against it: the hold
        # is the padlock's own state and shows there, so saying it twice only cost
        # this control a second color for something that is not about it.
        Button("genau_toggle_auto_advance", _advance_label(model),
               "Auto advance: move on to the next clip on a timer",
               width=BUTTON * 2 + GAP,
               lit=model.auto_advance),
        # Holding a clip only means anything inside auto advance, so outside it the
        # control is drawn faded and answers no press.  On is on, in the same white
        # every other switch here lights in — a hold is not a third kind of state.
        Button("genau_toggle_clip_lock", _GLYPHS["lock"],
               "Hold this clip against auto advance" if model.auto_advance
               else "Hold a clip — only while auto advance is armed",
               lit=model.clip_locked, dim=not model.auto_advance),
        Button("genau_cycle_shape", WAVE_ICON, f"Waveform: {shape_label(model.shape)}"),
        Button("quarter_button", _GLYPHS["quarter"], "Offset the stroke a ¼ cycle"),
    ]


def osr2_row(model: ConsoleModel) -> list[Button]:
    """The control that sits beside the OSR2 read-out.

    The broker is the service that talks to the OSR2 at all, so it acts on the
    device rather than on a player and shares the device's line.  It was a
    dashboard button before this HUD existed and wears its dashboard face again:
    the pink "B", blue while the service is up and red while it is down.
    """
    return [
        Button("broker_panel", BROKER_ICON,
               "OSR2 broker is running — press to stop it" if model.broker
               else "OSR2 broker is not running — press to start it",
               lit=model.broker, warn=not model.broker),
    ]


def place_rows(rows: list[list[Button]], *, x: int, y: int) -> list[tuple[Rect, Button]]:
    """Each button's rect, rows stacked down from ``(x, y)``.

    One placement feeds both the painting and the hit-testing, so what is drawn
    and what is clickable cannot drift apart.
    """
    placed: list[tuple[Rect, Button]] = []
    row_y = y
    for row in rows:
        run_x = x
        for index, button in enumerate(row):
            if index and _group_break(row, index):
                run_x += GROUP_GAP - GAP
            placed.append(((run_x, row_y, button.width, BUTTON), button))
            run_x += button.width + GAP
        row_y += BUTTON + ROW_GAP
    return placed


def _group_break(row: list[Button], index: int) -> bool:
    """Whether a wider gap belongs before ``row[index]``.

    The controls fall into groups that mean different things — stepping the video,
    nudging inside it, the file actions — and a run of evenly spaced squares reads
    as one long undifferentiated strip.
    """
    previous, current = row[index - 1], row[index]
    if not current.action or not previous.action:
        # A word naming the row stands apart from the controls; a value sitting
        # between a pair of them belongs with them, and pushing the − and + that
        # far apart made the pair read as two unrelated buttons.
        readout = current if not current.action else previous
        return readout.glyph.replace(" ", "").isalpha()
    return _family(previous.action) != _family(current.action)


# Genau controls whose command name does not begin with genau_.  Without this the
# ¼ offset fell out of the group it belongs to and opened a gap mid-row.
_GENAU_CONTROLS = frozenset({"quarter_button"})
# Recording a loop and saving what it caught: one job, two presses, and neither
# of them the library browser they used to be spaced alongside.
_CAPTURE_CONTROLS = frozenset({"nau_record_tap", "clipper_save"})
# The lock says what the *end* of the video does, where the four marks beside it
# each move the video now.  Sharing their prefix, it would have joined their run
# and read as a fifth step, which is the undifferentiated strip above.
_HOLD_CONTROLS = frozenset({"primary_lock"})
# Controls named for a player that belong with the file actions rather than with
# that player's transport: F-mode changes what there is to step through, the way
# the browser does, so it groups with the browser and not with prev/next.
_LIBRARY_CONTROLS = frozenset({"primary_fmode"})


def _family(action: str) -> str:
    """Which group of controls *action* belongs to."""
    # The three mode buttons are one group; genau_activate happens to start with
    # the Genau controls' prefix, which used to split the row after Hybrid.
    if action.endswith("_activate"):
        return "mode"
    if action in _GENAU_CONTROLS:
        return "genau_"
    if action in _CAPTURE_CONTROLS:
        return "capture"
    if action in _HOLD_CONTROLS:
        return "hold"
    if action in _LIBRARY_CONTROLS:
        return "file"
    # Stepping the video and nudging inside it are one run of four marks, so they
    # are one family: prev, back ten, forward ten, next, evenly spaced.
    for prefix in ("primary", "nau_speed", "genau_"):
        if action.startswith(prefix):
            return prefix
    return "file"


def row_width(rows: list[list[Button]]) -> int:
    """How wide the widest row runs — what the panel has to be to hold them."""
    placed = place_rows(rows, x=0, y=0)
    return max((rect[0] + rect[2] for rect, _b in placed), default=0)


def rows_height(rows: list[list[Button]]) -> int:
    """How tall the stack runs, with no trailing row gap."""
    return max(0, len(rows) * (BUTTON + ROW_GAP) - ROW_GAP)


def hit_test(placed: list[tuple[Rect, Button]], px: int, py: int) -> str:
    """The command for a press at ``(px, py)``, or "" over none of the buttons.

    A dimmed control is skipped: it is at its limit or has nothing to act on, so
    the press it would post is one Fun Time would ignore.
    """
    for (bx, by, bw, bh), button in placed:
        if button.dim or not button.action:
            continue
        if bx <= px < bx + bw and by <= py < by + bh:
            return button.action
    return ""


def tooltip_at(placed: list[tuple[Rect, Button]], px: int, py: int) -> str:
    """What the button under ``(px, py)`` is — every glyph here is cryptic on
    purpose, so each one names itself on hover.  A dimmed control still answers:
    knowing why it cannot be pressed is the point."""
    for (bx, by, bw, bh), button in placed:
        if bx <= px < bx + bw and by <= py < by + bh:
            return button.tooltip
    return ""
