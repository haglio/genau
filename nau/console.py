"""The controls on Nau's HUD, and where they sit.

Fun Time's dashboard used to draw a schematic of the two monitors with a little
box per player, and the primary player's box carried this row of buttons: step
the video, nudge it, open a file, save a clip, mark a loop, switch which player
owns the primary slot, and — when Genau is driving the device — its amplitude,
centre, speed, cruise, waveform and quarter-cycle offset.  Every one of them is
about the player that now draws its own HUD, so they belong on it.

Kept free of Pillow, like ``satellite.hud`` is, so the rows, the geometry and
the hit-testing are testable without a font.  :mod:`nau.hud` paints them.

The action on each button is a Fun Time dashboard command verbatim, because that
is where a press goes: appended to the same command file the dashboard writes, so
nothing new has to learn what these buttons mean.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

Rect = tuple[int, int, int, int]  # (x, y, w, h)

BUTTON = 18   # a square control; the wider ones are multiples plus the gaps
LABEL_W = 26  # a word naming the pair beside it, rather than a control
GAP = 4       # between buttons along a row
ROW_GAP = 5   # between rows
GROUP_GAP = 12  # between groups of buttons that mean different things


@dataclass(frozen=True)
class Button:
    """One item on the console: what it posts, what it looks like, how it is drawn.

    ``lit``, ``warn`` and ``hold`` are the live states — green for on, red for a
    suppression that is not the same as "off", blue for armed-but-sitting-still,
    which is the colour the drive readout gives the same condition.  ``dim`` is a
    control at the end of its range: drawn faded and left out of the hit targets,
    so a press that could do nothing is not offered.

    An empty ``action`` makes it a label: laid out in the row like anything else,
    drawn as a bare word with no box, and never a hit target.  That is how a pair
    of arrows gets told from the two pairs beside it.
    """

    action: str
    glyph: str
    tooltip: str
    width: int = BUTTON
    lit: bool = False
    warn: bool = False
    hold: bool = False
    dim: bool = False


@dataclass(frozen=True)
class ConsoleModel:
    """What Fun Time tells Nau about the primary slot, so the console can draw it.

    Nau knows what it is playing but nothing about the room around it: which mode
    the slot is in, what is driving the device, or where Genau's controls have hit
    their limits.  All of that arrives published, the way the satellites' maps do.
    """

    mode: str = "nau"
    takeover_allowed: bool = True
    cruise: bool = False
    # The other hands-free switch: cruise varies the stroke, auto advance moves
    # on to the next clip.  A held clip is auto advance still armed but sitting
    # still, which the button shows as its own state rather than as off.
    auto_advance: bool = False
    clip_locked: bool = False
    shape: str = "sine"
    # Which of Genau's controls have run out of range: "amp_max", "amp_min",
    # "ctr_max", "ctr_min", "spd_max", "spd_min".
    limits: frozenset[str] = field(default_factory=frozenset)
    # What is driving the device, in Fun Time's words — the dashboard drew this as
    # a box of its own with a cable running to the primary player.
    osr2: str = ""


def read_console(path: Path) -> ConsoleModel | None:
    """The console panel Fun Time published, or None when there is not a whole one.

    None means "keep the console you have": Fun Time replaces this file while Nau
    polls it, so a lost race must not empty the panel for a frame.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or "mode" not in raw:
        return None
    return ConsoleModel(
        mode=str(raw.get("mode", "nau")),
        takeover_allowed=bool(raw.get("takeover_allowed", True)),
        cruise=bool(raw.get("cruise", False)),
        shape=str(raw.get("shape", "sine") or "sine"),
        auto_advance=bool(raw.get("auto_advance", False)),
        clip_locked=bool(raw.get("clip_locked", False)),
        limits=frozenset(str(limit) for limit in raw.get("limits", []) or []),
        osr2=str(raw.get("osr2", "") or ""),
    )


# The glyphs, all from Segoe UI Symbol — Segoe UI Bold has none of them, and
# Pillow draws tofu where Qt used to fall back silently.
_GLYPHS = {
    "prev": "⏮", "next": "⏭", "back": "−", "fwd": "+",
    "open": "📂", "clip": "✂", "record": "⏺",
    "up": "▲", "down": "▼", "wave": "∿", "quarter": "¼",
}

_MODE_BUTTONS = (
    ("nau_activate", "Nau", "nau"),
    ("hybrid_activate", "Hybrid", "hybrid"),
    ("genau_activate", "Genau", "genau"),
)

# Each of Genau's three parameters: the label the pair sits under, the command
# stem, and the limit keys that grey each end out.
_DRIVE_PARAMS = (
    ("Amp", "genau_amplitude", "amp"),
    ("Ctr", "genau_center", "ctr"),
    ("Spd", "genau_speed", "spd"),
)


def genau_drives(mode: str) -> bool:
    """Whether a waveform is driving the device in *mode*.

    Only then do amplitude, centre, cruise and the rest mean anything — in Nau
    mode they would be a row of buttons with nothing behind them.  Genau mode is
    included for completeness; Nau is not on screen there to be asked.
    """
    return mode in ("genau", "hybrid")


def console_rows(model: ConsoleModel) -> list[list[Button]]:
    """The console's buttons, row by row, for the mode Fun Time says it is in."""
    rows = [
        [
            Button("primary_prev", _GLYPHS["prev"], "Previous video"),
            Button("primary_next", _GLYPHS["next"], "Next video"),
            Button("primary_nudge_prev", _GLYPHS["back"], "Back 10s"),
            Button("primary_nudge_next", _GLYPHS["fwd"], "Forward 10s"),
            Button("open_file_dialog", _GLYPHS["open"], "Open file browser"),
            Button("clipper_save", _GLYPHS["clip"], "Save clip"),
        ],
        [
            Button(action, label, f"{label} mode", width=BUTTON * 2 + GAP,
                   lit=model.mode == mode)
            for action, label, mode in _MODE_BUTTONS
        ],
    ]
    if model.mode == "nau":
        # Recording marks a loop in the video Nau is playing.  In Hybrid the slot
        # is shared with a waveform and there is no loop to mark.
        rows[0].append(Button("nau_record_tap", _GLYPHS["record"], "Record loop"))
    if genau_drives(model.mode):
        rows.append(_drive_row(model))
        rows.append([
            Button("genau_toggle_cruise", "cc", "Cruise control", lit=model.cruise),
            Button("genau_toggle_auto_advance", "aa",
                   "Auto advance: holding this clip" if model.clip_locked
                   else "Auto advance",
                   lit=model.auto_advance and not model.clip_locked,
                   hold=model.auto_advance and model.clip_locked),
            Button("genau_cycle_shape", _GLYPHS["wave"], f"Waveform: {model.shape}"),
            Button("quarter_button", _GLYPHS["quarter"], "Offset ¼ cycle"),
            Button("genau_toggle_auto", "GA",
                   "Genau takeover: allowed" if model.takeover_allowed
                   else "Genau takeover: suppressed",
                   lit=model.takeover_allowed, warn=not model.takeover_allowed),
        ])
    return rows


def _drive_row(model: ConsoleModel) -> list[Button]:
    """Amplitude, centre and speed, each a labelled up/down pair, greyed at its
    limits.  Without the labels the row is three identical pairs of arrows."""
    row: list[Button] = []
    for label, stem, key in _DRIVE_PARAMS:
        row.append(Button("", label, "", width=LABEL_W))
        row += [
            Button(f"{stem}_{end}", _GLYPHS[glyph], f"{label} {word}",
                   dim=f"{key}_{limit}" in model.limits)
            for end, glyph, word, limit in (("up", "up", "up", "max"),
                                            ("down", "down", "down", "min"))
        ]
    return row


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

    The controls fall into pairs and triples that mean different things — stepping
    the video, nudging inside it, the file actions — and a run of evenly spaced
    squares reads as one long undifferentiated strip.  Genau's parameters break
    every two, since each is an up/down pair.
    """
    previous, current = row[index - 1], row[index]
    if not current.action:
        return True  # a label opens the group it names
    if not previous.action:
        return False  # …and its own pair follows it close
    return _family(previous.action) != _family(current.action)


def _family(action: str) -> str:
    """Which group of controls *action* belongs to."""
    for prefix in ("primary_nudge", "primary", "genau_"):
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

    A dimmed control is skipped: it is at the end of its range, so the press it
    would post is one Fun Time would ignore.
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
