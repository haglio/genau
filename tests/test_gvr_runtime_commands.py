"""Every verb GenauVR's runtime accepts, against the state it is supposed to move.

``apply_runtime_command`` is the whole control surface: the voice listener and
the ``genau_vr_cmd.txt`` file channel both arrive here and nowhere else.  So the
table below is the contract — one row per verb, naming *exactly* what that verb
changes — and the assertion is that everything else stayed where it was.  A verb
rewired to a sibling action (AMP to the centre setter), mis-signed (SPEED_DOWN
speeding up) or inverted (PAUSE clearing the paused flag) moves a key the row
does not name, or fails to move the one it does, and dies here.

The collaborators are real: a real ``DirectControlState``, a real
``PlaybackEngine``, a real ``CruiseControlState``, a real ``threading.Event``.
Only the two the runtime reaches *out* through are stood in for — the clip
stepper, which is the app's own playlist move, and the audio sink, which would
otherwise open a mixer — and both stand-ins keep observable state rather than
recording calls.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager

import threading

import pytest

from genau_vr.cruise_control import CruiseControlState
from genau_vr.playback import DirectControlState, PlaybackEngine, WaveformShape
from genau_vr.controls import GenauVrControls
from genau_vr.runtime_commands import apply_runtime_command
from genau_vr.voice import VOICE_COMMANDS


@contextmanager
def _nothing_logged():
    """Collect the dispatcher's warnings for the duration of one call."""
    records: list[logging.LogRecord] = []

    class _Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger("genau_vr.runtime_commands")
    handler = _Collect()
    logger.addHandler(handler)
    previous, logger.propagate = logger.propagate, False
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.propagate = previous


class ClipStepper:
    """The app's playlist move, as the dispatcher sees it: a direction, in order."""

    def __init__(self) -> None:
        self.steps: list[int] = []

    def __call__(self, step: int) -> None:
        self.steps.append(step)


class AudioSink:
    """A level that moves, standing in for the mixer-backed AudioPlayer.

    Clamped the way the real one clamps, so a row can name a level rather than
    a call: the real ``AudioPlayer`` builds an SDL mixer in its constructor, and
    a table that ran 24 verbs through one would open 24 of them.
    """

    def __init__(self, volume: float = 0.25) -> None:
        self.volume = volume

    def adjust_volume(self, delta: float) -> None:
        self.volume = max(0.0, min(1.0, self.volume + delta))


class Runtime:
    """One dispatch's worth of collaborators, and what they say afterwards."""

    def __init__(self, **start) -> None:
        self.engine = PlaybackEngine(phase=start.get("phase", 0.5))
        self.paused = {"value": start.get("paused", False)}
        self.stepper = ClipStepper()
        self.audio = AudioSink()
        self.stop_event = threading.Event()
        self.cruise = CruiseControlState(active=start.get("cruise", False))
        self.direct = DirectControlState(
            playing=start.get("playing", True),
            speed=start.get("speed", 50),
            amplitude=start.get("amplitude", 60),
            intended_center=start.get("intended_center", 40),
            shape=start.get("shape", WaveformShape.TRIANGLE),
        )

    def apply(self, command: str, *, direct_state: object = ...) -> bool:
        """Run one verb; True when the dispatcher answered it.

        The dispatcher returns nothing — an unanswered verb goes on the log,
        which is the only place production can see it — so "was this verb
        answered?" is asked of the log, and every table below goes on asking
        it the same way.
        """
        with _nothing_logged() as unanswered:
            apply_runtime_command(command, GenauVrControls(
                rh_paused=self.paused,
                step_clip=self.stepper,
                direct_state=self.direct if direct_state is ... else direct_state,
                cruise_control_state=self.cruise,
                stop_event=self.stop_event,
                audio_player=self.audio,
            ))
        return not unanswered

    def state(self) -> dict:
        """Everything a verb could observably move, in one dict.

        Read as a whole rather than field by field so a row asserts what a verb
        does *and* what it leaves alone — the half that catches a verb wired to
        its neighbour's action.
        """
        return {
            "paused": self.paused["value"],
            "playing": self.direct.playing,
            "speed": self.direct.speed,
            "amplitude": self.direct.amplitude,
            "center": self.direct.center,
            "intended_center": self.direct.intended_center,
            "shape": self.direct.shape,
            "phase": round(self.engine.phase, 6),
            "cruise": self.cruise.active,
            "steps": tuple(self.stepper.steps),
            "volume": round(self.audio.volume, 6),
            "stopping": self.stop_event.is_set(),
        }


# verb, the state it starts from, and the ONLY keys it may move.
#
# The starting state is chosen so every move is visible: amplitude 60 leaves the
# centre free to travel (half-range 30, so 30..70), speed 50 is clear of both
# clamps, and TRIANGLE has a distinct neighbour in each direction.
HANDLED = [
    ("QUIT", {}, {"stopping": True}),
    ("PREV", {}, {"steps": (-1,)}),
    ("NEXT", {}, {"steps": (1,)}),
    ("PAUSE", {}, {"paused": True, "playing": False}),
    ("RESUME", {"paused": True, "playing": False}, {"paused": False, "playing": True}),
    ("SPEED_DOWN", {}, {"speed": 45}),
    ("SPEED_UP", {}, {"speed": 55}),
    ("AMPLITUDE_DOWN", {}, {"amplitude": 50}),
    ("AMPLITUDE_UP", {}, {"amplitude": 70}),
    ("CENTER_DOWN", {}, {"center": 35, "intended_center": 35}),
    ("CENTER_UP", {}, {"center": 45, "intended_center": 45}),
    ("CYCLE_SHAPE", {}, {"shape": WaveformShape.ROUNDED_SQUARE}),
    ("TOGGLE_CRUISE", {}, {"cruise": True}),
    ("TOGGLE_CRUISE", {"cruise": True}, {"cruise": False}),
    ("CRUISE_ON", {}, {"cruise": True}),
    ("CRUISE_OFF", {"cruise": True}, {"cruise": False}),
    ("VOLUME_UP", {}, {"volume": 0.35}),
    ("VOLUME_DOWN", {}, {"volume": 0.15}),
    # The three that carry a number.  AMP and CENTER land on different fields —
    # amplitude re-clamps the centre it already has, where CENTER sets the
    # centre the player asked for — which is what tells the two setters apart.
    ("AMP 80", {}, {"amplitude": 80}),
    ("CENTER 65", {}, {"center": 65, "intended_center": 65}),
    ("SPEED 90", {}, {"speed": 90}),
]


def _ids(rows):
    """Name each case by its verb, and by what it starts from when that differs."""
    return [f"{verb}-from-{sorted(start)}" if start else verb for verb, start, _ in rows]


@pytest.mark.parametrize("verb, start, moves", HANDLED, ids=_ids(HANDLED))
def test_a_verb_moves_what_it_names_and_nothing_else(verb, start, moves):
    runtime = Runtime(**start)
    before = runtime.state()

    handled = runtime.apply(verb)

    assert handled is True, f"{verb} was not recognised"
    assert runtime.state() == {**before, **moves}


class TestTheSpellingOfAVerb:
    def test_case_and_surrounding_space_do_not_matter(self):
        """The file channel writes what a voice listener heard, and the
        dashboard writes what a person typed."""
        runtime = Runtime()

        assert runtime.apply("  pause \n") is True
        assert runtime.state()["paused"] is True

    def test_a_numeric_verb_is_read_the_same_way(self):
        runtime = Runtime()

        assert runtime.apply("speed 90") is True
        assert runtime.state()["speed"] == 90


# verb, and the state it starts from — none of these may move anything.
REFUSED = [
    ("", {}),
    ("   ", {}),
    ("NOT_A_VERB", {}),
    ("AMP", {}),                  # a numeric verb with no number
    ("AMP eighty", {}),           # a number that is not one
    ("AMP 80 90", {}),            # split takes one argument, and this is two
    ("BRIGHTNESS 80", {}),        # a number, for a setter that does not exist
    ("NUDGE25", {}),              # a legacy spelling with no sender in any repo
    ("SLOW_DOWN", {}),            # likewise; the live one is SPEED_DOWN
    # No voice phrase says either, and the voice listener is the only thing
    # that writes genau_vr_cmd.txt, so neither could ever have been read here.
    ("OFFSET_QUARTER_CYCLE", {}),
    ("CYCLE_SHAPE_PREV", {}),
]


@pytest.mark.parametrize("verb, start", REFUSED,
                         ids=[repr(v) for v, _ in REFUSED])
def test_a_verb_the_runtime_does_not_know_changes_nothing(verb, start):
    runtime = Runtime(**start)
    before = runtime.state()

    handled = runtime.apply(verb)

    assert handled is False
    assert runtime.state() == before


class TestWhatTheRuntimeWasNotGiven:
    """A collaborator the app did not build is a verb the runtime refuses.

    Reported unhandled rather than silently swallowed: the caller logs it, and a
    verb that answered True while doing nothing would look like a working
    control.
    """

    ONLY_WITH_DIRECT_STATE = [
        "SPEED_DOWN", "SPEED_UP",
        "AMPLITUDE_DOWN", "AMPLITUDE_UP", "CENTER_DOWN", "CENTER_UP",
        "CYCLE_SHAPE",
        "AMP 80", "CENTER 65", "SPEED 90",
    ]

    @pytest.mark.parametrize("verb", ONLY_WITH_DIRECT_STATE)
    def test_a_stroke_verb_is_refused_without_the_stroke_state(self, verb):
        runtime = Runtime()

        assert runtime.apply(verb, direct_state=None) is False

    def test_pause_still_works_without_the_stroke_state(self):
        """The paused flag is the loop's own, so pausing never needed it."""
        runtime = Runtime()

        assert runtime.apply("PAUSE", direct_state=None) is True
        assert runtime.state()["paused"] is True

    @pytest.mark.parametrize("verb", ["QUIT", "VOLUME_UP", "CRUISE_ON"])
    def test_a_verb_whose_collaborator_is_missing_is_named_on_the_log(self, verb, caplog):
        """The stop event, the audio player and the cruise state, each left out.

        Naming it is the whole answer now: the dispatcher returns nothing, so a
        verb the app cannot honour is a log line rather than a flag nobody
        reads. Saying nothing would have the sender believe it landed.
        """
        runtime = Runtime()

        with caplog.at_level("WARNING", logger="genau_vr.runtime_commands"):
            apply_runtime_command(verb, GenauVrControls(
                rh_paused=runtime.paused, step_clip=runtime.stepper,
                direct_state=runtime.direct,
            ))

        assert verb in caplog.text
        assert runtime.state()["stopping"] is False


class TestTheVerbsVoiceControlCanSay:
    """Every phrase the listener maps has to reach a branch that handles it.

    An unhandled verb is invisible at runtime — the dispatcher returns False and
    the caller logs it — so a renamed branch would leave a spoken control dead
    with nothing red anywhere.  Asserting the two ends against each other is the
    only thing that notices; the pair of literal ``VOICE_COMMANDS["louder"] ==
    "VOLUME_UP"`` assertions this replaces restated the dict two lines above it.
    """

    @pytest.mark.parametrize("phrase, verb", sorted(VOICE_COMMANDS.items()))
    def test_every_spoken_phrase_names_a_verb_the_runtime_handles(self, phrase, verb):
        runtime = Runtime()

        assert runtime.apply(verb) is True, f"{phrase!r} says {verb!r}, which nothing handles"

    def test_every_verb_the_runtime_handles_has_a_phrase_that_reaches_it(self):
        """And the other way round, which is the half that rots quietly.

        ``genau_vr_cmd.txt`` has exactly one producer -- the voice listener --
        so a branch of the dispatcher with no phrase pointing at it can never
        fire.  Two sat there unreachable (OFFSET_QUARTER_CYCLE and
        CYCLE_SHAPE_PREV) with every test around them green.
        """
        spoken = {verb.split()[0] for verb in VOICE_COMMANDS.values()}
        handled = {verb.split()[0] for verb, _start, _moves in HANDLED}

        assert handled <= spoken, f"handled and unspeakable: {sorted(handled - spoken)}"

    def test_the_spoken_numbers_reach_the_setter_they_name(self):
        """The three numeric families are generated from a word list, so a
        broken generator would show up as every one of them landing nowhere."""
        runtime = Runtime()

        runtime.apply(VOICE_COMMANDS["amp fifty"])
        runtime.apply(VOICE_COMMANDS["center thirty"])
        runtime.apply(VOICE_COMMANDS["speed seventy"])

        assert (runtime.direct.amplitude, runtime.direct.intended_center,
                runtime.direct.speed) == (50, 30, 70)


def test_an_unknown_verb_is_named_on_the_log(caplog):
    """The dispatcher says so itself, because it is the only thing that knows.

    GenauVR's channel has one writer, the voice listener, so an unanswered
    verb means a phrase reached a branch that is no longer there — which is
    worth a line rather than silence.
    """
    runtime = Runtime()

    with caplog.at_level("WARNING", logger="genau_vr.runtime_commands"):
        apply_runtime_command("NOT_A_VERB", GenauVrControls(
            rh_paused=runtime.paused, step_clip=runtime.stepper,
            direct_state=runtime.direct))

    assert "NOT_A_VERB" in caplog.text


def test_a_verb_it_acts_on_says_nothing(caplog):
    runtime = Runtime()

    with caplog.at_level("WARNING", logger="genau_vr.runtime_commands"):
        apply_runtime_command("NEXT", GenauVrControls(
            rh_paused=runtime.paused, step_clip=runtime.stepper,
            direct_state=runtime.direct))

    assert caplog.records == []
