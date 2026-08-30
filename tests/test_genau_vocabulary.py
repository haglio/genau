"""The vocabulary Genau receives on, written down where a diff has to show it.

Genau is the *receiving* half of two contracts Fun Time owns: the verbs it
writes into ``genau_cmd.txt``, and the field names it reads back out of
``genau_status.txt``.  Neither has a schema anywhere — the verbs are bare
string literals inside a dispatcher and the fields are an f-string — so a
rename, a drop or a quietly-added spelling is invisible in review and silent at
runtime: an unknown verb is logged and ignored, and a renamed status field
reads as absent.

So the set is written out here, and gated from two sides that fail differently:

* **behavior** — every verb below is answered by a fully-wired dispatcher, and
  every retired spelling still is not.  This catches a verb *dropped* or
  *re-spelled* by a restructure, whatever shape the dispatcher takes.
* **source** — the uppercase literals in the package equal these verbs plus the
  named non-verbs.  This catches a verb *added*, which no behavioral probe can
  discover, and it holds whether the verbs live in an elif chain, a table, an
  enum or a module of their own.

Neither half alone is enough, which is why both are here.  Adding a verb means
editing this file, on purpose, in the same commit — which is the whole point.
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


# --------------------------------------------------------------------------
# Genau
# --------------------------------------------------------------------------

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
    "DISPLAY_ON": None,
    "DISPLAY_OFF": None,
    # The five that carry a value.
    "AMP": "50",
    "CENTER": "50",
    "SPEED": "50",
    "CLIP_SECONDS": "10",
    "SET_VOLUME": "40 0",
}

# Upper-case literals in ``genau/`` that are *not* genau_cmd verbs, each named
# for the protocol it does belong to.  Held as an equality with the verbs above
# so a new one is a deliberate line in a diff rather than a silent widening of
# what the scan tolerates.
GENAU_NOT_VERBS: dict[str, str] = {
    "AUTO": "genau/state.py — a UDP verb the broker sends",
    "BPM": "genau/state.py — a UDP verb the broker sends",
    "SYNC": "genau/state.py — a UDP verb the broker sends",
    "PARK": "genau/device_handoff.py — written to the broker, not read from Fun Time",
    "APPDATA": "genau/win32.py — an environment variable",
    "L0": "genau/tcode.py — the T-Code axis",
    "RGB": "genau/pygame_view.py — a pygame surface format",
    "RGBA": "genau/pygame_view.py — a pygame surface format",
    "T": "genau/cache_utils.py — an ISO-8601 date separator",
}

# The keys Genau's own window answers to, and the verb each one means.  Twelve
# of the sixteen: ESC, SPACE, `/` and Ctrl+Q are the window's own and have no
# verb (the `/` divergence is in CHANGELOG.md, 2026-08-30).
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


# --------------------------------------------------------------------------
# GenauVR
# --------------------------------------------------------------------------

GVR_VERBS: dict[str, str | None] = {
    "QUIT": None,
    "PREV": None,
    "NEXT": None,
    "PAUSE": None,
    "RESUME": None,
    "SPEED_DOWN": None,
    "SPEED_UP": None,
    "AMPLITUDE_DOWN": None,
    "AMPLITUDE_UP": None,
    "CENTER_DOWN": None,
    "CENTER_UP": None,
    "CYCLE_SHAPE": None,
    "TOGGLE_CRUISE": None,
    "CRUISE_ON": None,
    "CRUISE_OFF": None,
    "VOLUME_UP": None,
    "VOLUME_DOWN": None,
    "AMP": "50",
    "CENTER": "50",
    "SPEED": "50",
}

GVR_NOT_VERBS: dict[str, str] = {
    "CSV": "genau_vr/vr_runtime.py — an OpenXR structure-type suffix",
    "L0": "genau_vr/playback.py — the T-Code axis",
    "I": "genau_vr/playback.py — the T-Code interval suffix",
    "I": "genau_vr/playback.py — the T-Code interval suffix",
}

# Genau answers to fourteen verbs GenauVR does not: it has a clip folder to
# reorder, a lock, a HUD, a display flag and a console volume chip, and none of
# those exist in the headset.  GenauVR answers to two Genau does not — its own
# audio player's level.  Written down so the *divergence* is a reviewed fact and
# not something a reader has to diff two dispatchers to discover.
ONLY_GENAU = frozenset({
    "WEIRD", "LATEST", "SHUFFLE", "OFFSET_QUARTER_CYCLE", "CYCLE_SHAPE_PREV",
    "TOGGLE_LOCK", "LOCK_ON", "LOCK_OFF", "CLIP_SECONDS_DOWN", "CLIP_SECONDS_UP",
    "CLIP_SECONDS", "HUD_ON", "HUD_OFF", "DISPLAY_ON", "DISPLAY_OFF", "SET_VOLUME",
})
ONLY_GVR = frozenset({"VOLUME_UP", "VOLUME_DOWN"})


# --------------------------------------------------------------------------
# The two gates
# --------------------------------------------------------------------------


def _key_names(tree: ast.AST) -> dict[int, str]:
    """The ``key=`` a ``Verb(...)`` was declared with, by node id.

    A pygame constant's name is verb-shaped (``K_PERIOD``) but is not a verb, so
    the scan below has to tell the two apart by where they sit rather than by
    how they are spelled.  These get their own gate instead.
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


def _verb_shaped_literals(package: str) -> set[str]:
    return _scan(package)[0]


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
    """Send one line to a Genau dispatcher with every collaborator wired."""
    from genau.clip_advance import ClipAdvanceState
    from genau.controls import GenauControls
    from genau.engine import PlaybackEngine
    from genau.flags import Flag
    from genau.runtime_commands import apply_runtime_command
    from player_core.cruise_control import CruiseControlState
    from player_core.direct_control import DirectControlState

    with _unanswered("genau.runtime_commands") as refused:
        apply_runtime_command(line, GenauControls(
            engine=PlaybackEngine(phase=0.0, last_tick=0.0),
            paused=Flag(),
            step_clip=lambda _step: None,
            discard_clip=lambda: None,
            direct_state=DirectControlState(playing=True, speed=50, amplitude=60, center=40),
            cruise_control_state=CruiseControlState(),
            set_stroke_phase=lambda _phase: None,
            clip_advance_state=ClipAdvanceState(),
            stop_event=threading.Event(),
            hud=Flag(),
            display=Flag(on=True),
            set_volume=lambda _level, _muted: None,
            reorder_clips=lambda _recent: None,
        ))
    return not refused


def _gvr_answers(line: str) -> bool:
    """Send one line to a GenauVR dispatcher with every collaborator wired."""
    from genau_vr.controls import GenauVrControls
    from genau_vr.cruise_control import CruiseControlState
    from genau_vr.playback import DirectControlState
    from genau_vr.runtime_commands import apply_runtime_command

    class _Audio:
        volume = 0.25

        def adjust_volume(self, delta: float) -> None:
            self.volume += delta

    with _unanswered("genau_vr.runtime_commands") as refused:
        apply_runtime_command(line, GenauVrControls(
            step_clip=lambda _step: None,
            direct_state=DirectControlState(playing=True, speed=50, amplitude=60, center=40),
            cruise_control_state=CruiseControlState(),
            stop_event=threading.Event(),
            audio_player=_Audio(),
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

    def test_the_source_names_these_verbs_and_no_others(self):
        assert _verb_shaped_literals("genau") == set(GENAU_VERBS) | set(GENAU_NOT_VERBS)

    def test_every_spoken_phrase_names_a_verb(self):
        from genau.voice import VOICE_COMMANDS

        spoken = {phrase.split()[0] for phrase in VOICE_COMMANDS.values()}
        assert spoken <= set(GENAU_VERBS)

    def test_the_source_declares_these_keys_and_no_others(self):
        assert _scan("genau")[1] == set(GENAU_KEYS)

    def test_each_key_stands_for_the_verb_written_down_beside_it(self):
        from genau.controls import KEYS

        assert {name: verb.spelling for name, (_control, verb) in KEYS.items()} == GENAU_KEYS

    def test_genau_vr_declares_no_keys(self):
        """The headset has no keyboard; its controls arrive as verbs only."""
        assert _scan("genau_vr")[1] == set()

    def test_no_control_declares_a_verb_that_is_not_written_down(self):
        """The registry is where verbs are added, so it is where a widening of
        the vocabulary would first show."""
        from genau.controls import VERBS

        assert set(VERBS) <= set(GENAU_VERBS)


class TestGenauVrAnswersEveryVerbWrittenDown:
    @pytest.mark.parametrize("verb", sorted(GVR_VERBS))
    def test_a_verb_written_down_is_answered(self, verb):
        assert _gvr_answers(_spelling(verb, GVR_VERBS[verb])) is True

    def test_a_verb_nobody_sends_is_refused(self):
        assert _gvr_answers("EXAMPLE_VERB") is False
        assert _gvr_answers("EXAMPLE_VERB 7") is False

    def test_the_source_names_these_verbs_and_no_others(self):
        assert _verb_shaped_literals("genau_vr") == set(GVR_VERBS) | set(GVR_NOT_VERBS)

    def test_every_spoken_phrase_names_a_verb(self):
        from genau_vr.voice import VOICE_COMMANDS

        spoken = {phrase.split()[0] for phrase in VOICE_COMMANDS.values()}
        assert spoken <= set(GVR_VERBS)


class TestTheTwoDispatchersDivergeOnlyWhereSaid:
    """One vocabulary, two receivers — and the difference is a written fact.

    Both halves matter: a verb GenauVR silently stops answering would otherwise
    look like a widening of ONLY_GENAU, and a verb copied across from Genau
    would look like nothing at all.
    """

    def test_genau_answers_the_shared_verbs_and_its_own(self):
        assert set(GENAU_VERBS) - set(GVR_VERBS) == ONLY_GENAU

    def test_genau_vr_answers_the_shared_verbs_and_its_own(self):
        assert set(GVR_VERBS) - set(GENAU_VERBS) == ONLY_GVR


class TestTheStatusFileFunTimeReads:
    def test_it_publishes_exactly_these_fields_in_this_order(self):
        from genau.clip_advance import ClipAdvanceState
        from genau.status_writer import build_status_text
        from player_core.cruise_control import CruiseControlState
        from player_core.direct_control import DirectControlState

        text = build_status_text(
            DirectControlState(),
            CruiseControlState(),
            clip_advance=ClipAdvanceState(),
        )

        written = [line.split("=", 1)[0] for line in text.splitlines()]
        assert tuple(written) == GENAU_STATUS_FIELDS

    def test_every_line_is_a_key_and_a_value(self):
        """No field may go out bare — a reader splits on the first ``=``."""
        from genau.status_writer import build_status_text
        from player_core.cruise_control import CruiseControlState
        from player_core.direct_control import DirectControlState

        text = build_status_text(DirectControlState(), CruiseControlState())

        assert text.endswith("\n")
        assert all("=" in line for line in text.splitlines())
