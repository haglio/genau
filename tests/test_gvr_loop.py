"""GenauVR's frame loop, driven with a stand-in headset.

The loop was 134 lines inside a module that could not be imported without an
OpenXR runtime, so its five per-turn rules had never been exercised anywhere.
The session, renderer and window are stood in for here; everything else is real.
"""
from __future__ import annotations

import ast
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from genau_vr.cruise_control import CruiseControlState
from genau_vr.playback import DirectControlState, PlaybackEngine


class FakeView:
    """One eye, as the runtime describes it."""

    fov = SimpleNamespace(angle_left=-0.7, angle_right=0.7,
                          angle_up=0.7, angle_down=-0.7)
    pose = SimpleNamespace(
        orientation=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0))


class FakeSession:
    """A headset that answers for a fixed number of turns, then stops."""

    def __init__(self, turns: int = 1, *, ready: bool = True,
                 should_render: bool = True, views: int = 2,
                 close_after: int | None = None):
        self.running = True
        self.session_ready = ready
        self.thumbstick_y = 0.0
        self._turns = turns
        self._should_render = should_render
        self._views = [FakeView() for _ in range(views)]
        self._close_after = close_after
        self.calls: list[str] = []
        self.bound: list[int] = []
        self.released: list[int] = []
        self.frames_ended = 0
        self.controller_syncs = 0

    @property
    def window_close_requested(self) -> bool:
        return self._close_after is not None and self.calls.count("poll") > self._close_after

    def poll_events(self) -> None:
        self.calls.append("poll")
        if self.calls.count("poll") > self._turns:
            self.running = False

    def frame_begin(self):
        self.calls.append("frame_begin")
        return self._should_render, 123, self._views

    def sync_controller(self) -> None:
        self.controller_syncs += 1
        self.calls.append("sync_controller")

    def bind_eye_framebuffer(self, index: int) -> None:
        self.bound.append(index)
        self.calls.append(f"bind{index}")

    def release_eye_framebuffer(self, index: int) -> None:
        self.released.append(index)
        self.calls.append(f"release{index}")

    def frame_end(self, display_time, views) -> None:
        self.frames_ended += 1
        self.calls.append("frame_end")


class FakeRenderer:
    def __init__(self) -> None:
        self.uploads: list[int] = []
        self.eyes: list[int] = []

    def upload_frame(self, frame) -> None:
        self.uploads.append(int(frame[0, 0, 0]))

    def render_eye(self, index: int, inv_vp) -> None:
        self.eyes.append(index)


@pytest.fixture
def glfw_stub(monkeypatch):
    """The loop imports glfw inside itself; nothing here has a window."""
    stub = MagicMock()
    monkeypatch.setitem(sys.modules, "glfw", stub)
    return stub


def _frames(count: int) -> list[np.ndarray]:
    return [np.full((2, 2, 3), i, dtype=np.uint8) for i in range(count)]


def _run(session, renderer, *, commands=(), speed=50, clips=("alpha.mp4",),
         frames=4, playing=True, paused=False):
    from genau_vr.carousel import ClipCarousel
    from genau_vr.loop import controls_for, run_loop

    said = list(commands)
    engine = PlaybackEngine(last_tick=0.0)
    state = DirectControlState(playing=playing, speed=speed)
    carousel = ClipCarousel(
        [Path(name) for name in clips], _frames(frames),
        audio=MagicMock(), decode=lambda _path: _frames(frames),
    )
    controls = controls_for(carousel, engine, state, CruiseControlState(),
                            MagicMock(), threading.Event(), {"value": paused})
    run_loop(session, renderer, engine, controls, carousel, MagicMock(),
             Path("genau_vr_cmd.txt"),
             lambda _path: said.pop(0) if said else None)
    return engine, state


class TestOneTurnOfTheLoop:
    def test_it_polls_the_headset_and_ends_the_frame(self, glfw_stub):
        session, renderer = FakeSession(turns=1), FakeRenderer()

        _run(session, renderer)

        assert session.frames_ended == 1

    def test_it_draws_both_eyes_and_lets_go_of_each(self, glfw_stub):
        session, renderer = FakeSession(turns=1), FakeRenderer()

        _run(session, renderer)

        assert renderer.eyes == [0, 1]
        assert session.bound == [0, 1]
        assert session.released == [0, 1]

    def test_each_eye_is_let_go_of_before_the_next_is_bound(self, glfw_stub):
        """Bound twice over, the second eye draws into the first's framebuffer."""
        session, renderer = FakeSession(turns=1), FakeRenderer()

        _run(session, renderer)

        drawing = [c for c in session.calls if c.startswith(("bind", "release"))]
        assert drawing == ["bind0", "release0", "bind1", "release1"]

    def test_a_turn_the_runtime_says_not_to_render_still_ends_its_frame(self, glfw_stub):
        """The runtime hands out frames whether or not it wants them drawn, and
        an unclosed frame stalls the compositor."""
        session = FakeSession(turns=1, should_render=False)
        renderer = FakeRenderer()

        _run(session, renderer)

        assert renderer.eyes == []
        assert session.frames_ended == 1

    def test_a_turn_with_no_views_draws_nothing(self, glfw_stub):
        session, renderer = FakeSession(turns=1, views=0), FakeRenderer()

        _run(session, renderer)

        assert renderer.eyes == []
        assert session.frames_ended == 1

    def test_the_controller_is_asked_once_a_turn(self, glfw_stub):
        session, renderer = FakeSession(turns=3), FakeRenderer()

        _run(session, renderer)

        assert session.controller_syncs == 3


class TestWhenTheLoopStops:
    def test_a_session_the_runtime_ended_stops_it(self, glfw_stub):
        session, renderer = FakeSession(turns=2), FakeRenderer()

        _run(session, renderer)

        assert session.frames_ended == 2

    def test_the_little_window_closing_stops_it(self, glfw_stub):
        """The headset has no close box; that window is how a session started
        from a shortcut is ended without one."""
        session = FakeSession(turns=10, close_after=2)
        renderer = FakeRenderer()

        _run(session, renderer)

        assert session.frames_ended == 2

    def test_a_quit_command_stops_it(self, glfw_stub):
        session, renderer = FakeSession(turns=10), FakeRenderer()

        _run(session, renderer, commands=["QUIT"])

        assert session.frames_ended == 1


class TestWhileTheSessionIsNotReadyYet:
    def test_it_draws_nothing_and_does_not_ask_for_a_frame(self, glfw_stub):
        """OpenXR hands out no frames before it has begun the session, and
        asking for one is an error rather than a wait."""
        session = FakeSession(turns=2, ready=False)
        renderer = FakeRenderer()

        _run(session, renderer)

        assert "frame_begin" not in session.calls
        assert renderer.eyes == []

    def test_it_still_pumps_the_window(self, glfw_stub):
        """Left unpumped, the little window stops answering and Windows offers
        to kill it."""
        session = FakeSession(turns=2, ready=False)

        _run(session, FakeRenderer())

        assert glfw_stub.poll_events.called


class TestWhatACommandReaches:
    def test_a_verb_moves_the_hand_the_loop_is_following(self, glfw_stub):
        session, renderer = FakeSession(turns=1), FakeRenderer()

        _engine, state = _run(session, renderer, commands=["SPEED 90"])

        assert state.speed == 90

    def test_a_verb_that_steps_the_clip_moves_it(self, glfw_stub):
        session, renderer = FakeSession(turns=1), FakeRenderer()

        _run(session, renderer, commands=["NEXT"], clips=("alpha.mp4", "beta.mp4"))

        assert renderer.uploads == [0]


class TestSteppingTheClipFromAVerb:
    """`controls_for` is the join between the carousel and the engine, and the
    rule lives there rather than in the loop that calls it."""

    @staticmethod
    def _built(clips=("alpha.mp4", "beta.mp4"), phase=0.7):
        from genau_vr.carousel import ClipCarousel
        from genau_vr.loop import controls_for

        engine = PlaybackEngine(phase=phase, last_tick=0.0)
        carousel = ClipCarousel(
            [Path(name) for name in clips], _frames(4),
            audio=MagicMock(), decode=lambda _path: _frames(4),
        )
        controls = controls_for(carousel, engine, DirectControlState(playing=True),
                                CruiseControlState(), MagicMock(),
                                threading.Event(), {"value": False})
        return engine, carousel, controls

    def test_a_new_clip_starts_at_its_own_top(self):
        """A new clip has its own length; carrying the old phase across would
        open it somewhere arbitrary."""
        engine, carousel, controls = self._built()

        controls.step_clip(1)

        assert carousel.current_path == Path("beta.mp4")
        assert engine.phase == 0.0

    def test_a_step_that_goes_nowhere_leaves_the_phase_where_it_was(self):
        """One clip cannot be stepped away from, and restarting its phase would
        make the picture jump for nothing."""
        engine, _carousel, controls = self._built(clips=("alpha.mp4",))

        controls.step_clip(1)

        assert engine.phase == 0.7


class TestTheOrderOneTurnDoesThingsIn:
    """Read off the syntax tree: a reordering here leaves every unit green,
    because every part is right and only the sequence between them is not."""

    @staticmethod
    def _steps() -> list[str]:
        source = (Path(__file__).resolve().parents[1]
                  / "genau_vr" / "loop.py").read_text(encoding="utf-8")
        body = next(n for n in ast.walk(ast.parse(source))
                    if isinstance(n, ast.FunctionDef) and n.name == "run_loop")
        loop = next(n for n in ast.walk(body) if isinstance(n, ast.While))
        calls = [n for n in ast.walk(loop) if isinstance(n, ast.Call)]
        calls.sort(key=lambda n: (n.lineno, n.col_offset))
        return [ast.unparse(n.func) for n in calls]

    def _before(self, first: str, second: str) -> None:
        steps = self._steps()
        assert first in steps and second in steps
        assert steps.index(first) < steps.index(second), f"{first} must precede {second}"

    def test_the_command_is_acted_on_before_the_stroke_goes_out(self):
        """Drained after, a PAUSE is a stroke late every time."""
        self._before("apply_runtime_command", "tcode_sender.maybe_send")

    def test_the_engine_moves_before_the_frame_is_chosen_from_its_phase(self):
        self._before("update_engine", "carousel.frame_for_phase")

    def test_the_frame_is_uploaded_before_the_eyes_are_drawn(self):
        """Drawn first, both eyes show the previous frame."""
        self._before("renderer.upload_frame", "render_views")

    def test_the_controller_is_read_before_the_tilt_it_moves_is_used(self):
        self._before("session.sync_controller", "pitch.follow")
        self._before("pitch.follow", "render_views")

    def test_the_frame_is_ended_after_the_eyes_are_drawn(self):
        self._before("render_views", "session.frame_end")
