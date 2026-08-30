"""Every key in Genau's own window, against the state it is supposed to move.

The window's keys and the orchestrator's verbs are two ways into one control,
and until now they were two separate wires: a lambda in ``run_listener`` on one
side, a branch in the dispatcher on the other, with nothing asserting they meant
the same thing.  ``tests/test_genau_lifecycle.py`` pins key-to-callback and
``tests/test_genau_command_seam.py`` pins verb-to-state; between them sat the
callback-to-state half, which lived in ``run_listener`` and had no test at all.

So this drives keys against the real states, in the same shape the command seam
uses -- one row per key, what it moves and what it must leave alone -- and then
asks the two tables the question neither could ask alone: does the key do what
its verb does?
"""
from __future__ import annotations

import threading

import pygame
import pytest

from genau.clip_advance import ClipAdvanceState
from genau.controls import GenauControls
from genau.engine import PlaybackEngine
from genau.lifecycle import GenauLifecycleController
from player_core.cruise_control import CruiseControlState
from player_core.direct_control import DirectControlState, WaveformShape


class FakeRenderer:
    def prepare_active_clip_for_current_size(self) -> None:
        pass


class FakeSelection:
    def __init__(self) -> None:
        self.step_calls: list[int] = []
        self.discard_calls = 0

    def step(self, delta: int) -> None:
        self.step_calls.append(delta)

    def discard_current(self) -> bool:
        self.discard_calls += 1
        return True


class FakeNotifier:
    def __init__(self) -> None:
        self.visible_updates: list[bool] = []
        self.closed = 0

    def notify_visible(self, value: bool) -> None:
        self.visible_updates.append(value)

    def close(self) -> None:
        self.closed += 1


class Keys:
    """A Genau wired the way run_listener wires it, pressed at.

    The starting state matches the command seam's, so a key's row and its
    verb's row are read against the same numbers.
    """

    def __init__(self, **start):
        self.selection = FakeSelection()
        self.notifier = FakeNotifier()
        self.stop_event = threading.Event()
        self.engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        self.direct = DirectControlState(
            playing=bool(start.get("playing", False)),
            speed=start.get("speed", 50),
            amplitude=start.get("amplitude", 60),
            center=start.get("center", 40),
            intended_center=start.get("center", 40),
            shape=start.get("shape", WaveformShape.TRIANGLE),
        )
        self.cruise = CruiseControlState(active=bool(start.get("cruise", False)))
        self.advance = ClipAdvanceState(locked=bool(start.get("locked", False)))
        self.controls = GenauControls(
            engine=self.engine,
            rh_paused={"value": False},
            step_clip=self.selection.step,
            discard_clip=self.selection.discard_current,
            direct_state=self.direct,
            cruise_control_state=self.cruise,
            clip_advance_state=self.advance,
            stop_event=self.stop_event,
        )
        self.controller = _build(self)

    def press(self, key: int, mod: int = 0) -> None:
        self.controller._handle_key(
            pygame.event.Event(pygame.KEYDOWN, key=key, mod=mod),
        )

    def state(self) -> dict:
        return {
            "playing": self.direct.playing,
            "speed": self.direct.speed,
            "amplitude": self.direct.amplitude,
            "center": self.direct.center,
            "intended_center": self.direct.intended_center,
            "shape": self.direct.shape,
            "phase": round(self.engine.phase, 6),
            "cruise": self.cruise.active,
            "locked": self.advance.locked,
            "steps": tuple(self.selection.step_calls),
            "condemned": self.selection.discard_calls,
            "stopping": self.stop_event.is_set(),
        }


def _build(keys: Keys) -> GenauLifecycleController:
    """Wire the controller the way run_listener does.

    Transcribed from genau/app.py, which is the only place this wiring exists;
    ``pause_only`` is False here, which is Genau standalone.
    """
    from player_core.direct_control import space_action, toggle_playing

    return GenauLifecycleController(
        renderer=FakeRenderer(),
        selection=keys.selection,
        stop_event=keys.stop_event,
        notifier=keys.notifier,
        resize_delay_ms=75,
        quarter_offset=lambda: keys.engine.__setattr__(
            "phase", (keys.engine.phase + 0.25) % 1.0),
        on_toggle_playing=lambda: toggle_playing(keys.direct),
        on_pause_playing=lambda: space_action(keys.direct, pause_only=False),
        on_adjust_speed=lambda delta: _adjust("speed", keys.direct, delta),
        on_adjust_amplitude=lambda delta: _adjust("amplitude", keys.direct, delta),
        on_adjust_center=lambda delta: _adjust("center", keys.direct, delta),
        on_cycle_shape=lambda: _cycle(keys.direct),
        on_toggle_cruise=lambda: _toggle_cruise(keys.cruise),
        on_toggle_lock=lambda: _toggle_lock(keys.advance),
        on_weird_clip=keys.selection.discard_current,
    )


def _adjust(which, direct, delta):
    from player_core import direct_control

    getattr(direct_control, f"adjust_{which}")(direct, delta)


def _cycle(direct):
    from player_core.direct_control import cycle_shape

    cycle_shape(direct)


def _toggle_cruise(cruise):
    from player_core.cruise_control import toggle_cruise_control

    toggle_cruise_control(cruise)


def _toggle_lock(advance):
    from genau.clip_advance import toggle_lock

    toggle_lock(advance)


# key, modifier, what it starts from, and the ONLY keys it may move.
#
# The cluster is laid out like the arrow keys: K above for "condemn this one",
# M and . either side for previous and next, and , below K to hold the clip on
# screen against the advance.
PRESSES = [
    ("K_m", 0, {}, {"steps": (-1,)}),
    ("K_PERIOD", 0, {}, {"steps": (1,)}),
    ("K_k", 0, {}, {"condemned": 1}),
    ("K_COMMA", 0, {}, {"locked": True}),
    ("K_COMMA", 0, {"locked": True}, {"locked": False}),
    ("K_BACKSLASH", 0, {}, {"phase": 0.25}),
    ("K_j", 0, {}, {"speed": 45}),
    ("K_l", 0, {}, {"speed": 55}),
    ("K_7", 0, {}, {"amplitude": 50}),
    ("K_9", 0, {}, {"amplitude": 70}),
    ("K_u", 0, {}, {"center": 35, "intended_center": 35}),
    ("K_o", 0, {}, {"center": 45, "intended_center": 45}),
    ("K_i", 0, {}, {"shape": WaveformShape.ROUNDED_SQUARE}),
    ("K_SLASH", 0, {}, {"cruise": True}),
    ("K_SLASH", 0, {"cruise": True}, {"cruise": False}),
    # The two that have no verb: the window's own play/pause pair.
    ("K_ESCAPE", 0, {}, {"playing": True}),
    ("K_ESCAPE", 0, {"playing": True}, {"playing": False}),
    ("K_SPACE", 0, {}, {"playing": True}),
    ("K_SPACE", 0, {"playing": True}, {"playing": False}),
]


def _ids(rows):
    return [f"{key}-from-{sorted(start)}" if start else key
            for key, _mod, start, _moves in rows]


def _a_stack_the_device_was_following():
    """One wave, so letting go has a phase to hand back."""
    from player_core.wave_stack import Ramp, Wave, WaveStack

    def steady(value: float) -> Ramp:
        """A dial that is not on its way anywhere."""
        return Ramp(start=value, end=value)

    return WaveStack(waves=(Wave(
        speed=steady(50), amplitude=steady(60), center=steady(40), phase=0.375,
    ),))


@pytest.mark.parametrize("key, mod, start, moves", PRESSES, ids=_ids(PRESSES))
def test_a_key_moves_what_it_names_and_nothing_else(key, mod, start, moves):
    keys = Keys(**start)
    before = keys.state()

    keys.press(getattr(pygame, key), mod)

    assert keys.state() == {**before, **moves}


def test_a_key_genau_does_not_use_moves_nothing():
    keys = Keys()
    before = keys.state()

    keys.press(pygame.K_x)

    assert keys.state() == before


def test_ctrl_q_asks_the_window_to_close_and_moves_no_control():
    keys = Keys()
    before = keys.state()

    keys.press(pygame.K_q, pygame.KMOD_CTRL)

    assert keys.stop_event.is_set() is True
    assert keys.state() == {**before, "stopping": True}
    assert keys.notifier.visible_updates == [False]


class TestAKeyAndItsVerbAgree:
    """The question neither table could ask alone.

    Thirteen of Genau's keys are a second way to send a verb.  If the two ever
    stop meaning the same thing the app still runs -- one path moves the control
    and the other moves it differently -- which is exactly the drift that made
    every control a four-to-six file edit.
    """

    # key -> the verb that is supposed to mean the same thing.
    SAME = {
        "K_m": "PREV",
        "K_PERIOD": "NEXT",
        "K_k": "WEIRD",
        "K_COMMA": "TOGGLE_LOCK",
        "K_BACKSLASH": "OFFSET_QUARTER_CYCLE",
        "K_j": "SPEED_DOWN",
        "K_l": "SPEED_UP",
        "K_7": "AMPLITUDE_DOWN",
        "K_9": "AMPLITUDE_UP",
        "K_u": "CENTER_DOWN",
        "K_o": "CENTER_UP",
        "K_i": "CYCLE_SHAPE",
    }

    @pytest.mark.parametrize("key, verb", sorted(SAME.items()))
    def test_the_key_moves_what_the_verb_moves(self, key, verb):
        from test_genau_command_seam import SEAM

        rows = [moves for spelling, start, moves in SEAM
                if spelling == verb and not start]
        assert len(rows) == 1, f"{verb} has no plain row in the command seam"
        pressed = [moves for pressed_key, _mod, start, moves in PRESSES
                   if pressed_key == key and not start]
        assert len(pressed) == 1

        assert pressed[0] == rows[0]

    def test_the_slash_key_and_toggle_cruise_do_not_yet_agree(self):
        """The one that drifted, written down rather than fixed here.

        TOGGLE_CRUISE hands the phase of the wave the device was following back
        to the sender, so the single stroke picks up where cruise control left
        it.  The `/` key discards that phase, so the stroke resumes on its own
        free-running one and the hand jumps.  Both reach the same
        toggle_cruise_control; only one reads what it returns.

        Held rather than fixed because this item is behaviour-preserving -- see
        CHANGELOG.md, 2026-08-30 -- and the fix is to give the key the verb.
        """
        from genau.runtime_commands import apply_runtime_command

        handed_back: list[float] = []
        keys = Keys(cruise=True)
        keys.cruise.stack = _a_stack_the_device_was_following()
        keys.controls.set_stroke_phase = handed_back.append

        keys.press(pygame.K_SLASH)

        assert keys.cruise.active is False, "the key did turn cruise control off"
        assert handed_back == [], "the key discards the phase"

        keys.cruise.active = True
        keys.cruise.stack = _a_stack_the_device_was_following()
        apply_runtime_command("TOGGLE_CRUISE", keys.controls)

        assert handed_back == [0.375], "the verb hands it to the sender"
