"""What a control can reach.

Genau's controls are spoken to from three places -- a verb in ``genau_cmd.txt``,
a key in the window, a press on the console -- and every one of them has to be
able to move the same handful of things: the hand's own state, the cruise stack,
the clip advance, the two boxes an orchestrator flips, the clip sequence.

Passing those one at a time is what made adding a control a four-to-six file
edit: a keyword parameter on the dispatcher, another on the refresh controller,
an attribute to store it and a line to hand it on.  They travel together here
instead, built once where the app is wired and handed whole.

Optional means *this build did not wire it* -- a Genau launched without a cruise
stack, a test that only cares about the clip sequence.  A verb whose collaborator
is absent is refused and logged rather than half-acted-on, which is the behavior
:func:`genau.runtime_commands.apply_runtime_command` documents.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

from player_core.cruise_control import (
    CruiseControlState,
    disable_cruise_control,
    enable_cruise_control,
    toggle_cruise_control,
)
from player_core.robot_hand import (
    RobotHandState,
    adjust_amplitude,
    adjust_center,
    adjust_speed,
    cycle_shape,
    set_amplitude,
    set_center,
    set_speed,
)

from .clip_advance import (
    ClipAdvanceState,
    adjust_interval,
    set_interval,
    set_locked,
    toggle_lock,
)
from .control_registry import Control, Verb, bind, bind_keys
from .engine import PlaybackEngine
from .flags import Flag


@dataclass
class GenauControls:
    """Everything one command, key or console press may move."""

    engine: PlaybackEngine
    paused: Flag
    step_clip: Callable[[int], None]
    condemn_clip: Callable[[], None] | None = None
    robot_hand: RobotHandState | None = None
    cruise_control_state: CruiseControlState | None = None
    set_stroke_phase: Callable[[float], None] | None = None
    clip_advance_state: ClipAdvanceState | None = None
    stop_event: threading.Event | None = None
    hud: Flag | None = None
    set_volume: Callable[[int, bool], None] | None = None
    reorder_clips: Callable[[bool], None] | None = None


# The acts below all take these controls and the rest of the line, and say
# whether they could.
Act = Callable[[GenauControls, str], bool]

# Fun Time's spelling for the quarter-turn of the stroke's phase.  Named because
# two spellings of it once shipped side by side, which is the drift a literal per
# branch invites.
QUARTER_CYCLE_OFFSET_COMMAND = "OFFSET_QUARTER_CYCLE"


def _stepper(step: int) -> Act:
    """A verb that nudges the hand's speed by a fixed amount."""
    def act(controls: GenauControls, _value: str) -> bool:
        adjust_speed(controls.robot_hand, step)
        return True
    return act


def _amplitude_step(step: int) -> Act:
    def act(controls: GenauControls, _value: str) -> bool:
        adjust_amplitude(controls.robot_hand, step)
        return True
    return act


def _center_step(step: int) -> Act:
    def act(controls: GenauControls, _value: str) -> bool:
        adjust_center(controls.robot_hand, step)
        return True
    return act


def _shape_step(step: int) -> Act:
    def act(controls: GenauControls, _value: str) -> bool:
        cycle_shape(controls.robot_hand, step)
        return True
    return act


def _number_setter(setter) -> Act:
    """A verb that names the value outright: ``AMP 50``, ``SPEED 90``.

    A value that is not a whole number is refused rather than rounded or
    defaulted -- what arrived was not the command it looked like.
    """
    def act(controls: GenauControls, value: str) -> bool:
        try:
            number = int(value)
        except ValueError:
            return False
        setter(controls.robot_hand, number)
        return True
    return act


def _handed_back(controls: GenauControls, phase) -> None:
    """Cruise control letting go says where the single wave should pick up — at
    the phase of the wave that had most of the travel, which is the one the
    device was mostly following.  Nowhere to put it (a build with no sender) and
    the stroke simply resumes on its own free-running phase."""
    if phase is not None and controls.set_stroke_phase is not None:
        controls.set_stroke_phase(phase)


def _cruise_toggled(controls: GenauControls, _value: str) -> bool:
    _handed_back(controls, toggle_cruise_control(controls.cruise_control_state))
    return True


def _cruise_on(controls: GenauControls, _value: str) -> bool:
    enable_cruise_control(controls.cruise_control_state)
    return True


def _cruise_off(controls: GenauControls, _value: str) -> bool:
    _handed_back(controls, disable_cruise_control(controls.cruise_control_state))
    return True


def _lock_toggled(controls: GenauControls, _value: str) -> bool:
    toggle_lock(controls.clip_advance_state)
    return True


def _lock_set(locked: bool) -> Act:
    def act(controls: GenauControls, _value: str) -> bool:
        set_locked(controls.clip_advance_state, locked)
        return True
    return act


def _interval_step(step: int) -> Act:
    def act(controls: GenauControls, _value: str) -> bool:
        adjust_interval(controls.clip_advance_state, step)
        return True
    return act


def _interval_named(controls: GenauControls, value: str) -> bool:
    """"clip seconds thirty" names the seconds a clip holds the screen.  It says
    nothing about the lock: a held clip stays held, and this is the pace it will
    move at once it is let go."""
    try:
        seconds = int(value)
    except ValueError:
        return False
    set_interval(controls.clip_advance_state, seconds)
    return True


def _quit(controls: GenauControls, _value: str) -> bool:
    controls.stop_event.set()
    return True


def _step_clip(step: int) -> Act:
    def act(controls: GenauControls, _value: str) -> bool:
        controls.step_clip(step)
        return True
    return act


def _condemn(controls: GenauControls, _value: str) -> bool:
    controls.condemn_clip()
    return True


def _reorder(recent: bool) -> Act:
    def act(controls: GenauControls, _value: str) -> bool:
        controls.reorder_clips(recent)
        return True
    return act


def _offset_quarter_cycle(controls: GenauControls, _value: str) -> bool:
    controls.engine.phase = (controls.engine.phase + 0.25) % 1.0
    return True


def _playing(playing: bool) -> Act:
    """PAUSE and RESUME move both halves of one fact.

    The box is what an orchestrator's paused file feeds and what the tick reads;
    the hand's own flag is what the stroke follows.  A build with no hand still
    answers -- the room is paused either way.
    """
    def act(controls: GenauControls, _value: str) -> bool:
        controls.paused.on = not playing
        if controls.robot_hand is not None:
            controls.robot_hand.playing = playing
        return True
    return act


def _flag_set(name: str, value: bool) -> Act:
    def act(controls: GenauControls, _value: str) -> bool:
        getattr(controls, name).on = value
        return True
    return act


def _volume_shown(controls: GenauControls, value: str) -> bool:
    """``SET_VOLUME <level> [muted]`` — the sound level Fun Time is publishing.

    Genau neither owns the level (the orchestrator does, for the whole primary
    display) nor plays the audio: a companion process carries the clip music.
    What arrives here is only what the chip Genau draws should show, which is why
    the mute rides alongside the level — a level of zero cannot say whether the
    speaker is off or turned all the way down, nor what unmuting returns to.

    The mute is optional so an orchestrator that sends the level alone still
    moves the slider rather than being ignored outright.
    """
    said = value.split()
    try:
        level = int(said[0])
        muted = bool(int(said[1])) if len(said) > 1 else False
    except (IndexError, ValueError):
        return False
    controls.set_volume(level, muted)
    return True


# One entry per thing a person can move.  Add a control by adding a record here;
# nothing else in the app needs to learn its name.
CONTROLS: tuple[Control, ...] = (
    Control(
        name="speed",
        needs=("robot_hand",),
        verbs=(
            Verb("SPEED_DOWN", _stepper(-5), key="K_j"),
            Verb("SPEED_UP", _stepper(5), key="K_l"),
            Verb("SPEED", _number_setter(set_speed), takes_a_value=True),
        ),
    ),
    Control(
        name="amplitude",
        needs=("robot_hand",),
        verbs=(
            Verb("AMPLITUDE_DOWN", _amplitude_step(-10), key="K_7"),
            Verb("AMPLITUDE_UP", _amplitude_step(10), key="K_9"),
            Verb("AMP", _number_setter(set_amplitude), takes_a_value=True),
        ),
    ),
    Control(
        name="center",
        needs=("robot_hand",),
        verbs=(
            Verb("CENTER_DOWN", _center_step(-5), key="K_u"),
            Verb("CENTER_UP", _center_step(5), key="K_o"),
            Verb("CENTER", _number_setter(set_center), takes_a_value=True),
        ),
    ),
    Control(
        name="shape",
        needs=("robot_hand",),
        verbs=(
            Verb("CYCLE_SHAPE", _shape_step(1), key="K_i"),
            Verb("CYCLE_SHAPE_PREV", _shape_step(-1)),
        ),
    ),
    Control(
        name="cruise",
        needs=("cruise_control_state",),
        verbs=(
            Verb("TOGGLE_CRUISE", _cruise_toggled, key="K_SLASH"),
            Verb("CRUISE_ON", _cruise_on),
            Verb("CRUISE_OFF", _cruise_off),
        ),
    ),
    # The lock, under the same three verbs Nau answers to, because it is the same
    # thing on both: hold what is on screen, or let it move on.  Whichever player
    # owns the main slot gets them, and the one padlock on the console is what
    # sends them.
    Control(
        name="lock",
        needs=("clip_advance_state",),
        verbs=(
            Verb("TOGGLE_LOCK", _lock_toggled, key="K_COMMA"),
            Verb("LOCK_ON", _lock_set(True)),
            Verb("LOCK_OFF", _lock_set(False)),
        ),
    ),
    # How long a clip holds the screen, a second at a time.  Named for the number
    # rather than for the auto-advance that spends it, so the verb reads as what
    # the orchestrator's reference shows and what its speaker says aloud.
    Control(
        name="clip_seconds",
        needs=("clip_advance_state",),
        verbs=(
            Verb("CLIP_SECONDS_DOWN", _interval_step(-1)),
            Verb("CLIP_SECONDS_UP", _interval_step(1)),
            Verb("CLIP_SECONDS", _interval_named, takes_a_value=True),
        ),
    ),
    Control(
        name="quit",
        needs=("stop_event",),
        verbs=(Verb("QUIT", _quit),),
    ),
    Control(
        name="clip",
        verbs=(Verb("PREV", _step_clip(-1), key="K_m"),
            Verb("NEXT", _step_clip(1), key="K_PERIOD"),),
    ),
    Control(
        name="condemn",
        needs=("condemn_clip",),
        verbs=(Verb("WEIRD", _condemn, key="K_k"),),
    ),
    # The two browse orders every player in the room has, said to the one player
    # with no playlist file to hand it: Genau owns its own sequence, so the order
    # is a verb rather than a rewritten list, and answering it rescans the clips
    # folder — which is most of what Latest is for.
    Control(
        name="browse_order",
        needs=("reorder_clips",),
        verbs=(Verb("LATEST", _reorder(True)), Verb("SHUFFLE", _reorder(False))),
    ),
    Control(
        name="quarter_cycle",
        verbs=(Verb(QUARTER_CYCLE_OFFSET_COMMAND, _offset_quarter_cycle,
                    key="K_BACKSLASH"),),
    ),
    Control(
        name="pause",
        verbs=(Verb("PAUSE", _playing(False)), Verb("RESUME", _playing(True))),
    ),
    Control(
        name="hud",
        needs=("hud",),
        verbs=(
            Verb("HUD_ON", _flag_set("hud", True)),
            Verb("HUD_OFF", _flag_set("hud", False)),
        ),
    ),
    Control(
        name="volume",
        needs=("set_volume",),
        verbs=(Verb("SET_VOLUME", _volume_shown, takes_a_value=True),),
    ),
)


VERBS = bind(CONTROLS)
KEYS = bind_keys(CONTROLS)
