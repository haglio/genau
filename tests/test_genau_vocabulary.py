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
* **the registry** — the verbs it declares are exactly these, and the keys it
  declares mean exactly these verbs.  This catches a verb *added* there without
  a line here.
* **the window** — nothing under ``genau/`` spells a verb or declares a key.
  A verb literal back in this package is a control plumbed by hand again,
  which is what moving the registry out ended.
"""
from __future__ import annotations

import ast
import logging
import pathlib
import re
import threading
from contextlib import contextmanager

import pytest

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
    "LATEST": None,
    "SHUFFLE": None,
    "OFFSET_QUARTER_CYCLE": None,
    "PAUSE": None,
    "RESUME": None,
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
    "TOGGLE_LOCK": None,
    "LOCK_ON": None,
    "LOCK_OFF": None,
    "CLIP_SECONDS_DOWN": None,
    "CLIP_SECONDS_UP": None,
    "HUD_ON": None,
    "HUD_OFF": None,
    # The five that carry a value.
    "AMP": "50",
    "CENTER": "50",
    "SPEED": "50",
    "CLIP_SECONDS": "10",
    "SET_VOLUME": "40 0",
}

# Upper-case literals in ``genau/`` that are *not* genau_cmd verbs, each named
# for what it does belong to.  Held as an equality with the scan so a new one is
# a deliberate line in a diff rather than a silent widening of what the scan
# tolerates.
GENAU_NOT_VERBS: dict[str, str] = {
    "RGB": "genau/pygame_view.py — a pygame surface format",
    "RGBA": "genau/pygame_view.py — a pygame surface format",
}

# The keys Genau's own window answers to, and the verb each one means.  Thirteen
# of the sixteen: ESC, SPACE and Ctrl+Q are the window's own and have no verb.
#
# Laid out like the arrow keys for the clip cluster: K above for "condemn this
# one", M and . either side for previous and next, and , below K for the lock.
GENAU_KEYS: dict[str, str] = {
    "K_j": "SPEED_DOWN",
    "K_l": "SPEED_UP",
    "K_7": "AMPLITUDE_DOWN",
    "K_9": "AMPLITUDE_UP",
    "K_u": "CENTER_DOWN",
    "K_o": "CENTER_UP",
    "K_i": "CYCLE_SHAPE",
    "K_m": "PREV",
    "K_PERIOD": "NEXT",
    "K_k": "WEIRD",
    "K_COMMA": "TOGGLE_LOCK",
    "K_BACKSLASH": "OFFSET_QUARTER_CYCLE",
    "K_SLASH": "TOGGLE_CRUISE",
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
    "locked",
    "clip",
    "shape",
    "amp_at_max",
    "amp_at_min",
    "ctr_at_max",
    "ctr_at_min",
    "spd_at_max",
    "spd_at_min",
    "hud",
)


def _key_names(tree: ast.AST) -> dict[int, str]:
    """The ``key=`` a ``Verb(...)`` was declared with, by node id.

    A pygame constant's name is verb-shaped (``K_PERIOD``) but is not a verb, so
    the scan below has to tell the two apart by where they sit rather than by
    how they are spelled.
    """
    named: dict[int, str] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Verb"):
            continue
        for keyword in node.keywords:
            if keyword.arg == "key" and isinstance(keyword.value, ast.Constant):
                named[id(keyword.value)] = keyword.value.value
    return named


def _scan(package: str) -> tuple[set[str], set[str]]:
    """Every verb-shaped string constant in a package's source, and its keys.

    Read off the syntax tree rather than by importing, so a module that needs a
    platform this machine has not got still contributes its verbs.
    """
    verbs: set[str] = set()
    keys: set[str] = set()
    for path in sorted((REPO_DIR / package).rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        declared_keys = _key_names(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if id(node) in declared_keys:
                keys.add(node.value)
            elif _VERB_SHAPED.match(node.value):
                verbs.add(node.value)
    return verbs, keys


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
    from player_core.clip_advance import ClipAdvanceState
    from player_core.cruise_control import CruiseControlState
    from player_core.flag import Flag
    from player_core.genau_controls import GenauControls, apply_runtime_command
    from player_core.robot_hand import RobotHandState
    from player_core.robot_hand_beat import BeatEngine

    with _unanswered("player_core.genau_controls") as refused:
        apply_runtime_command(line, GenauControls(
            engine=BeatEngine(phase=0.0, last_tick=0.0),
            paused=Flag(),
            step_clip=lambda _step: None,
            condemn_clip=lambda: None,
            robot_hand=RobotHandState(playing=True, speed=50, amplitude=60, center=40),
            cruise_control_state=CruiseControlState(),
            set_stroke_phase=lambda _phase: None,
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

    def test_the_registry_declares_these_verbs_and_no_others(self):
        """The registry is where verbs are added, so it is where a widening of
        the vocabulary would first show -- and a verb it stopped declaring is one
        Fun Time still sends."""
        from player_core.genau_controls import VERBS

        assert set(VERBS) == set(GENAU_VERBS)

    def test_each_key_stands_for_the_verb_written_down_beside_it(self):
        from player_core.genau_controls import KEYS

        assert {name: verb.spelling for name, (_control, verb) in KEYS.items()} == GENAU_KEYS


class TestTheWindowSpellsNoVerbOfItsOwn:
    """The registry left this package, and with it every verb.  A verb-shaped
    literal back in ``genau/`` is a control plumbed by hand again -- a branch in
    a key handler, a spelling in the composition root -- which is what a control
    being declared once put an end to.
    """

    def test_the_window_names_no_verb(self):
        assert _scan("genau")[0] == set(GENAU_NOT_VERBS)

    def test_the_window_declares_no_key(self):
        """A key goes beside its verb in the registry, nowhere else."""
        assert _scan("genau")[1] == set()

    def test_the_window_keeps_exactly_the_two_keys_that_have_no_verb(self):
        """The registry is where a key goes.  Two cannot be there: ESC and SPACE
        are two spellings of play/pause with two rules and no verb between them.
        Anything else added beside them is a key plumbed by hand again, which is
        what this item removed -- so the set is held as an equality.
        """
        lifecycle = REPO_DIR / "genau" / "lifecycle.py"
        tree = ast.parse(lifecycle.read_text(encoding="utf-8"), filename=str(lifecycle))
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "keymap"]

        assert len(calls) == 1, "the window builds its keymap in one place"
        assert {kw.arg for kw in calls[0].keywords} == {"K_ESCAPE", "K_SPACE"}


class TestTheStatusFileFunTimeReads:
    def test_it_publishes_exactly_these_fields_in_this_order(self):
        from player_core.clip_advance import ClipAdvanceState
        from player_core.cruise_control import CruiseControlState
        from player_core.genau_status import build_status_text
        from player_core.robot_hand import RobotHandState

        text = build_status_text(
            RobotHandState(),
            CruiseControlState(),
            clip_advance=ClipAdvanceState(),
        )

        written = [line.split("=", 1)[0] for line in text.splitlines()]
        assert tuple(written) == GENAU_STATUS_FIELDS

    def test_every_line_is_a_key_and_a_value(self):
        """No field may go out bare — a reader splits on the first ``=``."""
        from player_core.cruise_control import CruiseControlState
        from player_core.genau_status import build_status_text
        from player_core.robot_hand import RobotHandState

        text = build_status_text(RobotHandState(), CruiseControlState())

        assert text.endswith("\n")
        assert all("=" in line for line in text.splitlines())
