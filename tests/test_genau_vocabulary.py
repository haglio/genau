"""The vocabulary Genau receives on, written down where a diff has to show it.

Genau is the *receiving* half of two contracts Fun Time owns: the verbs it
writes into ``genau_cmd.txt``, and the field names it reads back out of
``genau_status.txt``.  Neither has a schema anywhere — the verbs are string
literals inside a registry and the fields are an f-string — so a rename, a drop
or a quietly-added spelling is invisible in review and silent at runtime: an
unknown verb is logged and ignored, and a renamed status field reads as absent.

The registry that answers the verbs lives in ``player_core`` now, so a second
shell (Fun Time's headset) can run it; this window's contract with Fun Time is
still this repo's to keep.  So the set is written out here and gated from three
sides:

* **behavior** — every verb below is answered by the dispatcher this window
  runs, fully wired, and every retired spelling still is not.  This catches a
  verb *dropped* or *re-spelled* in the engine.
* **the registry** — the verbs it declares include every one of these.  This
  catches a verb *dropped* there while Fun Time still sends it.
* **the window** — nothing under ``genau/`` spells a verb or reads a key.  A
  verb literal back in this package is a control plumbed by hand again, and a
  key read here is a keyboard of Genau's own beside the room's.
"""
from __future__ import annotations

import ast
import logging
import pathlib
import re
import threading
from contextlib import contextmanager

import pytest
from player_core.clip_advance import ClipAdvanceState
from player_core.cruise_control import CruiseControlState
from player_core.flag import Flag
from player_core.genau_controls import VERBS, GenauControls, apply_runtime_command
from player_core.genau_status import build_status_text
from player_core.learned_model import LearnedModel
from player_core.learned_motion import LearnedMotionState
from player_core.robot_hand import RobotHandState
from player_core.robot_hand_beat import BeatEngine

REPO_DIR = pathlib.Path(__file__).resolve().parents[1]

# What a verb looks like on the wire: upper case, words joined by underscores.
_VERB_SHAPED = re.compile(r"^[A-Z][A-Z0-9_]*$")

# Every verb ``genau_cmd.txt`` may carry.  The value beside each is the argument
# a probe sends it, or None when the verb stands alone.
GENAU_VERBS: dict[str, str | None] = {
    "QUIT": None,
    "PREV": None,
    "NEXT": None,
    "WEIRD": None,
    "FLIP_ENDS": None,
    "LATEST": None,
    "SHUFFLE": None,
    "OFFSET_QUARTER_CYCLE": None,
    "PAUSE": None,
    "RESUME": None,
    "PARK": None,
    "RETRACT": None,
    "SPEED_DOWN": None,
    "SPEED_UP": None,
    "AMPLITUDE_DOWN": None,
    "AMPLITUDE_UP": None,
    "CENTER_DOWN": None,
    "CENTER_UP": None,
    "CYCLE_SHAPE": None,
    "CYCLE_SHAPE_PREV": None,
    "TOGGLE_CRUISE": None,
    "CRUISE_ON": None,
    "CRUISE_OFF": None,
    "TOGGLE_LEARNED": None,
    "LEARNED_ON": None,
    "LEARNED_OFF": None,
    "TOGGLE_LOCK": None,
    "LOCK_ON": None,
    "LOCK_OFF": None,
    "CLIP_SECONDS_DOWN": None,
    "CLIP_SECONDS_UP": None,
    "HUD_ON": None,
    "HUD_OFF": None,
    # The six that carry a value.
    "AMP": "50",
    "CENTER": "50",
    "SPEED": "50",
    "CLIP_SECONDS": "10",
    "SET_VOLUME": "40 0",
    # Whether the motion reaches the OSR2 at all.  PAUSE is the other half of
    # this pair and stops the room; this one leaves the clips running and sends
    # the device nothing, which is how an orchestrator lets go of it.
    "SET_TCODE_ENABLED": "0",
}

# Upper-case literals in ``genau/`` that are *not* genau_cmd verbs, each named
# for what it does belong to.  Held as an equality with the scan so a new one is
# a deliberate line in a diff rather than a silent widening of what the scan
# tolerates.
GENAU_NOT_VERBS: dict[str, str] = {
    "RGB": "genau/pygame_view.py — a pygame surface format",
    "RGBA": "genau/pygame_view.py — a pygame surface format",
}

# Spellings that must stay refused.  Two were aliases no sender in the family
# ever used; three named the auto-advance rather than the number of seconds it
# spends, and were retired when the verb was renamed.  Fun Time's genau-mode
# Clip-seconds buttons still post the old pair (held bug 19) — which is a
# fun_time-side fix, so the answer here has to keep being "no".
GENAU_RETIRED = ("NUDGE25", "SLOW_DOWN", "ADVANCE_UP", "ADVANCE_DOWN", "ADVANCE 30")

# The fields ``genau_status.txt`` publishes, in the order they are written.
# fun_time's dashboard, dispatch loop and sequencer all read this file by key.
GENAU_STATUS_FIELDS = (
    "cruise",
    "learned",
    "locked",
    "clip",
    "flipped",
    "shape",
    "amp_at_max",
    "amp_at_min",
    "ctr_at_max",
    "ctr_at_min",
    "spd_at_max",
    "spd_at_min",
    "hud",
)


def _scan(package: str) -> set[str]:
    """Every verb-shaped string constant in a package's source.

    Read off the syntax tree rather than by importing, so a module that needs a
    platform this machine has not got still contributes its verbs.
    """
    verbs: set[str] = set()
    for path in sorted((REPO_DIR / package).rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        verbs |= {node.value for node in ast.walk(tree)
                  if isinstance(node, ast.Constant) and isinstance(node.value, str)
                  and _VERB_SHAPED.match(node.value)}
    return verbs


def _key_events_read(package: str) -> list[str]:
    """Every place under *package* that reads a key off pygame's event queue."""
    return [f"{path.name}:{node.lineno}"
            for path in sorted((REPO_DIR / package).rglob("*.py"))
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, ast.Attribute) and node.attr in ("KEYDOWN", "KEYUP")]


@contextmanager
def _unanswered(logger_name: str):
    """Collect the dispatcher's warnings — its only report of a verb it refused."""
    records: list[logging.LogRecord] = []

    class _Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger(logger_name)
    handler = _Collect()
    logger.addHandler(handler)
    previous, logger.propagate = logger.propagate, False
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.propagate = previous


def _genau_answers(line: str) -> bool:
    """Send one line to the dispatcher this window runs, every collaborator wired."""
    with _unanswered("player_core.genau_controls") as refused:
        apply_runtime_command(line, GenauControls(
            engine=BeatEngine(phase=0.0, last_tick=0.0),
            paused=Flag(),
            step_clip=lambda _step: None,
            condemn_clip=lambda: None,
            robot_hand=RobotHandState(playing=True, speed=50, amplitude=60, center=40),
            cruise_control_state=CruiseControlState(),
            learned_motion_state=LearnedMotionState(model=LearnedModel()),
            set_motion_phase=lambda _phase: None,
            clip_advance_state=ClipAdvanceState(),
            stop_event=threading.Event(),
            hud=Flag(),
            set_volume=lambda _level, _muted: None,
            reorder_clips=lambda _recent: None,
        ))
    return not refused


def _spelling(verb: str, argument: str | None) -> str:
    return verb if argument is None else f"{verb} {argument}"


class TestGenauAnswersEveryVerbWrittenDown:
    @pytest.mark.parametrize("verb", sorted(GENAU_VERBS))
    def test_a_verb_written_down_is_answered(self, verb):
        assert _genau_answers(_spelling(verb, GENAU_VERBS[verb])) is True

    @pytest.mark.parametrize("spelling", GENAU_RETIRED)
    def test_a_retired_spelling_is_still_refused(self, spelling):
        assert _genau_answers(spelling) is False

    def test_a_verb_nobody_sends_is_refused(self):
        assert _genau_answers("EXAMPLE_VERB") is False
        assert _genau_answers("EXAMPLE_VERB 7") is False

    def test_the_registry_declares_every_verb_written_down(self):
        """The registry is where verbs are added, so it is where a widening of
        the vocabulary would first show -- and a verb it stopped declaring is one
        Fun Time still sends."""
        # Every spelling written down is answered.  Not the other way round: a
        # verb player_core adds lands there first, pinned by its own
        # tests/test_genau_controls.py, and is written down here when this
        # window takes it up -- so the family's gate, which runs this suite
        # against a candidate player_core, does not refuse every addition.
        assert set(GENAU_VERBS) <= set(VERBS)


class TestTheWindowSpellsNoVerbOfItsOwn:
    """The registry left this package, and with it every verb.  A verb-shaped
    literal back in ``genau/`` is a control plumbed by hand again -- a branch in
    a key handler, a spelling in the composition root -- which is what a control
    being declared once put an end to.
    """

    def test_the_window_names_no_verb(self):
        assert _scan("genau") == set(GENAU_NOT_VERBS)

    def test_the_window_reads_no_key(self):
        """Genau runs only inside Fun Time, whose hotkeys are the room's keyboard;
        a key read here reached Genau without the session knowing, and went on
        answering while OmniPause had the room's keys switched off."""
        assert _key_events_read("genau") == []


class TestTheStatusFileFunTimeReads:
    def test_it_publishes_exactly_these_fields_in_this_order(self):
        text = build_status_text(
            RobotHandState(),
            CruiseControlState(),
            clip_advance=ClipAdvanceState(),
        )

        written = [line.split("=", 1)[0] for line in text.splitlines()]
        # The fields written down come out in this order; one player_core adds
        # ahead of this window taking it up may sit among them.
        assert tuple(field for field in written if field in GENAU_STATUS_FIELDS) == GENAU_STATUS_FIELDS
        assert set(GENAU_STATUS_FIELDS) <= set(written)

    def test_every_line_is_a_key_and_a_value(self):
        """No field may go out bare — a reader splits on the first ``=``."""
        text = build_status_text(RobotHandState(), CruiseControlState())

        assert text.endswith("\n")
        assert all("=" in line for line in text.splitlines())
