"""Every verb, driven the way Fun Time drives it: through the command file.

``tests/test_genau_runtime_commands.py`` calls the dispatcher directly, and
``tests/test_genau_refresh_controller.py`` builds a tick.  Between them sits the
wiring neither one watches: the refresh controller stores thirteen collaborators
and hands them to the dispatcher under thirteen names, and a name that stops
matching is silent -- the verb arrives, no branch can act on it, and the tick
goes on.  Six of the thirteen have no test that crosses the seam at all.

So this drives the whole path once per verb: a line written into a real
``genau_cmd.txt``, drained by the real file channel inside a real
``refresh()``, and asserted against the one thing it is supposed to move --
*and* against everything it must leave alone, which is the half that catches a
verb wired to its neighbour's collaborator.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from genau.clip_advance import ClipAdvanceState
from genau.controls import GenauControls
from genau.engine import PlaybackEngine
from genau.refresh_controller import GenauRefreshController
from genau.state import SharedState
from player_core.cruise_control import CruiseControlState
from player_core.direct_control import DirectControlState, WaveformShape

from test_genau_refresh_controller import (
    FakeLoader,
    FakeNotifier,
    FakeRenderer,
    FakeSelection,
    FakeTCodeSender,
)

# One frozen instant for the whole tick, so the engine's phase only moves when a
# verb moves it.
NOW = 5.0


class Seam:
    """A Genau with every collaborator wired, spoken to through its command file.

    The starting state is chosen so every move is visible: amplitude 60 leaves
    the centre free to travel (30..70), speed 50 is clear of both clamps, and
    TRIANGLE has a distinct neighbour in each direction.
    """

    def __init__(self, tmp_path: Path, **start):
        self.paused = {"value": bool(start.get("paused", False))}
        self.hud = {"active": bool(start.get("hud", False))}
        self.display = {"active": bool(start.get("display", True))}
        self.direct = DirectControlState(
            playing=bool(start.get("playing", False)),
            speed=start.get("speed", 50),
            amplitude=start.get("amplitude", 60),
            center=start.get("center", 40),
            intended_center=start.get("center", 40),
            shape=start.get("shape", WaveformShape.TRIANGLE),
        )
        self.cruise = CruiseControlState(active=bool(start.get("cruise", False)))
        self.advance = ClipAdvanceState(
            locked=bool(start.get("locked", False)),
            interval=start.get("interval", 20),
        )
        self.engine = PlaybackEngine(phase=0.0, last_tick=NOW)
        self.selection = FakeSelection()
        self.tcode = FakeTCodeSender()
        self.volumes: list[tuple[int, bool]] = []
        self.reorders: list[bool] = []
        self.stop_event = _Stop()
        self.command_file = tmp_path / "genau_cmd.txt"

        self.controller = GenauRefreshController(
            controls=GenauControls(
                engine=self.engine,
                rh_paused=self.paused,
                step_clip=self.selection.step,
                discard_clip=self.selection.discard_current,
                direct_state=self.direct,
                cruise_control_state=self.cruise,
                set_stroke_phase=self.tcode.set_stroke_phase,
                clip_advance_state=self.advance,
                stop_event=self.stop_event,
                hud_state=self.hud,
                display_state=self.display,
                set_volume=lambda level, muted: self.volumes.append((level, muted)),
                reorder_clips=self.reorders.append,
            ),
            state=SharedState(),
            loader=FakeLoader(),
            notifier=FakeNotifier(),
            renderer=FakeRenderer(path=Path("example.mp4")),
            selection=self.selection,
            command_file=self.command_file,
            paused_file=tmp_path / "genau_paused.txt",
            beats_per_loop=4.0,
            bpm_smoothing=0.5,
            sync_strength=0.5,
            set_loading_text=lambda _text: None,
            logger=MagicMock(),
            now_source=lambda: NOW,
            read_paused_state=lambda _path, logger=None: self.paused["value"],
            tcode_sender=self.tcode,
        )

    def send(self, line: str) -> None:
        """Write one line where Fun Time writes it, then run one tick."""
        self.command_file.write_text(line + "\n", encoding="utf-8")
        self.controller.refresh()

    def state(self) -> dict:
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
            "locked": self.advance.locked,
            "interval": self.advance.interval,
            "steps": tuple(self.selection.step_calls),
            "condemned": self.selection.discard_calls,
            "reorders": tuple(self.reorders),
            "volumes": tuple(self.volumes),
            "hud": self.hud["active"],
            "display": self.display["active"],
            "stopping": self.stop_event.is_set(),
        }


class _Stop:
    """A stop flag the tick can set without ending the test's own loop."""

    def __init__(self) -> None:
        self._set = False

    def set(self) -> None:
        self._set = True

    def is_set(self) -> bool:
        return self._set


# verb, what it starts from, and the ONLY keys it may move.
SEAM = [
    ("QUIT", {}, {"stopping": True}),
    ("PREV", {}, {"steps": (-1,)}),
    ("NEXT", {}, {"steps": (1,)}),
    ("WEIRD", {}, {"condemned": 1}),
    ("LATEST", {}, {"reorders": (True,)}),
    ("SHUFFLE", {}, {"reorders": (False,)}),
    ("OFFSET_QUARTER_CYCLE", {}, {"phase": 0.25}),
    ("PAUSE", {"playing": True}, {"paused": True, "playing": False}),
    ("RESUME", {"paused": True}, {"paused": False, "playing": True}),
    ("SPEED_DOWN", {}, {"speed": 45}),
    ("SPEED_UP", {}, {"speed": 55}),
    ("AMPLITUDE_DOWN", {}, {"amplitude": 50}),
    ("AMPLITUDE_UP", {}, {"amplitude": 70}),
    ("CENTER_DOWN", {}, {"center": 35, "intended_center": 35}),
    ("CENTER_UP", {}, {"center": 45, "intended_center": 45}),
    ("CYCLE_SHAPE", {}, {"shape": WaveformShape.ROUNDED_SQUARE}),
    ("CYCLE_SHAPE_PREV", {}, {"shape": WaveformShape.SINE}),
    ("TOGGLE_CRUISE", {}, {"cruise": True}),
    ("TOGGLE_CRUISE", {"cruise": True}, {"cruise": False}),
    ("CRUISE_ON", {}, {"cruise": True}),
    ("CRUISE_OFF", {"cruise": True}, {"cruise": False}),
    ("TOGGLE_LOCK", {}, {"locked": True}),
    ("TOGGLE_LOCK", {"locked": True}, {"locked": False}),
    ("LOCK_ON", {}, {"locked": True}),
    ("LOCK_OFF", {"locked": True}, {"locked": False}),
    ("CLIP_SECONDS_DOWN", {}, {"interval": 19}),
    ("CLIP_SECONDS_UP", {}, {"interval": 21}),
    ("HUD_ON", {}, {"hud": True}),
    ("HUD_OFF", {"hud": True}, {"hud": False}),
    ("DISPLAY_ON", {"display": False}, {"display": True}),
    ("DISPLAY_OFF", {}, {"display": False}),
    # The five that carry a value.
    ("AMP 80", {}, {"amplitude": 80}),
    ("CENTER 65", {}, {"center": 65, "intended_center": 65}),
    ("SPEED 90", {}, {"speed": 90}),
    ("CLIP_SECONDS 30", {}, {"interval": 30}),
    ("SET_VOLUME 40 1", {}, {"volumes": ((40, True),)}),
]


def _ids(rows):
    return [f"{verb}-from-{sorted(start)}" if start else verb for verb, start, _ in rows]


@pytest.mark.parametrize("verb, start, moves", SEAM, ids=_ids(SEAM))
def test_a_verb_reaches_its_collaborator_and_moves_nothing_else(verb, start, moves, tmp_path):
    seam = Seam(tmp_path, **start)
    before = seam.state()

    seam.send(verb)

    assert seam.state() == {**before, **moves}


def test_a_tick_with_no_command_moves_nothing(tmp_path):
    """The baseline the rows above are read against: a bare tick is inert."""
    seam = Seam(tmp_path)
    before = seam.state()

    seam.controller.refresh()

    assert seam.state() == before


def test_every_verb_genau_answers_is_driven_here(tmp_path):
    """The rows above are the vocabulary, or they are not a seam test.

    A verb added to the dispatcher without a row here would cross the seam
    untested, which is the exact gap this module exists to close.
    """
    from test_genau_vocabulary import GENAU_VERBS

    driven = {verb.split()[0] for verb, _start, _moves in SEAM}
    assert driven == set(GENAU_VERBS)
