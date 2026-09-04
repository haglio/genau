"""What a GenauVR control can reach, and what its controls are.

The same shape Genau's controls use -- :mod:`genau.control_registry` -- against
GenauVR's own collaborators, which are not Genau's: there is no window to draw a
console on, no clip folder to reorder, no HUD and no display flag, and the sound
is this app's own rather than a level an orchestrator publishes.  Nine controls
where Genau has sixteen; the divergence is written down and gated in
tests/test_genau_vocabulary.py.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

from genau.control_registry import Control, Verb, bind

from .cruise_control import (
    CruiseControlState,
    disable_cruise_control,
    enable_cruise_control,
    toggle_cruise_control,
)
from .playback import (
    DirectControlState,
    adjust_amplitude,
    adjust_center,
    adjust_speed,
    cycle_shape,
    set_amplitude,
    set_center,
    set_speed,
)

# How far one press of the volume moves it.
VOLUME_STEP = 0.1


@dataclass
class GenauVrControls:
    """Everything one command may move.

    Optional means *this build did not wire it* -- a headset brought up without
    a mixer, a test that only cares about the clip list.  A verb whose
    collaborator is absent is refused and logged rather than half-acted-on.
    """

    step_clip: Callable[[int], None]
    direct_state: DirectControlState | None = None
    cruise_control_state: CruiseControlState | None = None
    stop_event: threading.Event | None = None
    audio_player: object | None = None


Act = Callable[[GenauVrControls, str], bool]


def _quit(controls: GenauVrControls, _value: str) -> bool:
    controls.stop_event.set()
    return True


def _step_clip(step: int) -> Act:
    def act(controls: GenauVrControls, _value: str) -> bool:
        controls.step_clip(step)
        return True
    return act


def _playing(playing: bool) -> Act:
    """PAUSE and RESUME, on the one flag GenauVR has.

    Genau carries this twice -- a box fed by the paused file an orchestrator
    writes, and the hand's own flag -- because there the two have separate
    sources.  GenauVR has no paused file and never had: the box arrived with the
    copy, was written on the same line as the hand every time, and read nowhere
    else.  There is one fact here, and it is the hand's.
    """
    def act(controls: GenauVrControls, _value: str) -> bool:
        controls.direct_state.playing = playing
        return True
    return act


def _hand_step(move) -> Act:
    def act(controls: GenauVrControls, _value: str) -> bool:
        move(controls.direct_state)
        return True
    return act


def _number_setter(setter) -> Act:
    """A verb that names the value outright: ``AMP 50``, ``SPEED 90``.

    A value that is not a whole number is refused rather than rounded or
    defaulted -- what arrived was not the command it looked like.
    """
    def act(controls: GenauVrControls, value: str) -> bool:
        try:
            number = int(value)
        except ValueError:
            return False
        setter(controls.direct_state, number)
        return True
    return act


def _cruise(move) -> Act:
    def act(controls: GenauVrControls, _value: str) -> bool:
        move(controls.cruise_control_state)
        return True
    return act


def _volume_step(delta: float) -> Act:
    def act(controls: GenauVrControls, _value: str) -> bool:
        controls.audio_player.adjust_volume(delta)
        return True
    return act


CONTROLS: tuple[Control, ...] = (
    Control(
        name="speed",
        needs=("direct_state",),
        verbs=(
            Verb("SPEED_DOWN", _hand_step(lambda hand: adjust_speed(hand, -5))),
            Verb("SPEED_UP", _hand_step(lambda hand: adjust_speed(hand, 5))),
            Verb("SPEED", _number_setter(set_speed), takes_a_value=True),
        ),
    ),
    Control(
        name="amplitude",
        needs=("direct_state",),
        verbs=(
            Verb("AMPLITUDE_DOWN", _hand_step(lambda hand: adjust_amplitude(hand, -10))),
            Verb("AMPLITUDE_UP", _hand_step(lambda hand: adjust_amplitude(hand, 10))),
            Verb("AMP", _number_setter(set_amplitude), takes_a_value=True),
        ),
    ),
    Control(
        name="center",
        needs=("direct_state",),
        verbs=(
            Verb("CENTER_DOWN", _hand_step(lambda hand: adjust_center(hand, -5))),
            Verb("CENTER_UP", _hand_step(lambda hand: adjust_center(hand, 5))),
            Verb("CENTER", _number_setter(set_center), takes_a_value=True),
        ),
    ),
    Control(
        name="shape",
        needs=("direct_state",),
        verbs=(Verb("CYCLE_SHAPE", _hand_step(cycle_shape)),),
    ),
    Control(
        name="cruise",
        needs=("cruise_control_state",),
        verbs=(
            Verb("TOGGLE_CRUISE", _cruise(toggle_cruise_control)),
            Verb("CRUISE_ON", _cruise(enable_cruise_control)),
            Verb("CRUISE_OFF", _cruise(disable_cruise_control)),
        ),
    ),
    Control(
        name="volume",
        needs=("audio_player",),
        verbs=(
            Verb("VOLUME_UP", _volume_step(VOLUME_STEP)),
            Verb("VOLUME_DOWN", _volume_step(-VOLUME_STEP)),
        ),
    ),
    Control(name="quit", needs=("stop_event",), verbs=(Verb("QUIT", _quit),)),
    Control(
        name="clip",
        verbs=(Verb("PREV", _step_clip(-1)), Verb("NEXT", _step_clip(1))),
    ),
    Control(
        name="pause",
        needs=("direct_state",),
        verbs=(Verb("PAUSE", _playing(False)), Verb("RESUME", _playing(True))),
    ),
)

VERBS = bind(CONTROLS)
