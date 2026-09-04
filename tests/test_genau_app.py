"""Genau's own module: what it wires together before the loop starts.

``run_listener`` cannot be run here -- it opens an SDL window, binds a UDP port
and spawns a decode thread -- which is why it sat at a third of its lines
covered while being the second-hottest file in the repo.  What is testable is
the *wiring*: which part is handed what, and in which order.  That is also
where the parts can be joined up wrong while every unit test in the suite stays
green, because every unit is correct and only the joins between them are not.

So the joins are read off the syntax tree, the way tests/test_nau_app.py reads
Nau's and for the same reason.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "genau" / "app.py"


def _calls(where: ast.AST, spelling: str) -> list[ast.Call]:
    return [n for n in ast.walk(where)
            if isinstance(n, ast.Call) and ast.unparse(n.func) == spelling]


def _call(where: ast.AST, spelling: str) -> ast.Call:
    """The one call written exactly as *spelling* in *where*."""
    found = _calls(where, spelling)
    assert len(found) == 1, f"expected one {spelling}(), found {len(found)}"
    return found[0]


def _said(node: ast.AST) -> str:
    return ast.unparse(node)


def _keyword(call: ast.Call, name: str) -> str:
    for keyword in call.keywords:
        if keyword.arg == name:
            return _said(keyword.value)
    raise AssertionError(f"{_said(call.func)}() was given no {name}=")


def _module() -> ast.Module:
    return ast.parse(APP.read_text(encoding="utf-8"), filename=str(APP))


def _function(name: str) -> ast.FunctionDef:
    found = [n for n in ast.walk(_module())
             if isinstance(n, ast.FunctionDef) and n.name == name]
    assert len(found) == 1, f"expected one {name}(), found {len(found)}"
    return found[0]


def _startup() -> ast.FunctionDef:
    """Whichever function builds the window today.

    Named by what it does rather than by where it lives, so splitting
    run_listener into composed parts moves this test's subject rather than
    breaking it.
    """
    tree = ast.parse(APP.read_text(encoding="utf-8"), filename=str(APP))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and _calls(node, "PygameView"):
            return node
    raise AssertionError("nothing in genau/app.py builds a PygameView")


class TestWhatHappensBeforeTheWindow:
    """The decode of the first clip is the longest thing at startup and the one
    thing the window does not need, so it runs beside the window rather than in
    front of it.  Both halves of that are load-bearing and neither is visible
    from any unit."""

    def test_the_first_clip_starts_decoding_before_the_window_is_built(self):
        """Started after, the window comes up and then freezes for the decode --
        which is the whole of what the thread is for."""
        startup = _startup()
        started = _call(startup, "preload.start")
        built = _call(startup, "PygameView")

        assert started.lineno < built.lineno

    def test_the_decode_is_waited_for_only_after_everything_else_is_wired(self):
        """The wait is what makes the overlap worth having: move it up next to
        the start and the thread buys nothing at all."""
        startup = _startup()
        waited = _call(startup, "preload.wait")

        assert waited.lineno > _call(startup, "PygameView").lineno
        assert waited.lineno > _call(startup, "GenauRefreshController").lineno
        assert waited.lineno > _call(startup, "GenauLifecycleController").lineno

    def test_the_first_clip_is_put_on_screen_after_the_decode_is_waited_for(self):
        """Ahead of the wait it would show the clip before its frames are in the
        cache, and the cache write would then land on a clip already up."""
        startup = _startup()

        assert (_call(startup, "selection.set_current_clip").lineno
                > _call(startup, "preload.wait").lineno)

    def test_the_clip_the_thread_decodes_is_the_one_the_sequence_opens_on(self):
        """A start-clip an orchestrator named moves the sequence's head, so the
        head has to be read after that and not from the scan."""
        startup = _startup()
        head = [n for n in ast.walk(startup)
                if isinstance(n, ast.Assign)
                and _said(n.targets[0]) == "first_clip_path"]

        assert len(head) == 1
        assert _said(head[0].value) == "clip_sequence.current_path"
        assert head[0].lineno > _call(startup, "ClipSequenceController").lineno


class TestTheLoopAndTheTeardown:
    def test_each_turn_reads_the_window_then_refreshes_then_waits(self):
        """Refreshing before the events are read paints a frame against input
        one turn stale; waiting first spends the frame budget before any work."""
        loop = next(n for n in ast.walk(_startup()) if isinstance(n, ast.While))
        order = [_said(n.value.func) for n in loop.body if isinstance(n, ast.Expr)]

        assert order == ["lifecycle.process_events", "refresh_controller.refresh",
                         "view.clock.tick"]

    def test_the_device_is_let_go_of_before_the_window_goes(self):
        """Destroying the window first would leave the sender open across the
        teardown with nothing driving it."""
        startup = _startup()

        assert (_call(startup, "drive.tcode_sender.close").lineno
                < _call(startup, "view.destroy").lineno)


class TestTheOneHandEveryPartIsGiven:
    """Genau has exactly one RobotHandState, and four parts move or read it.

    Build a second anywhere in here and the app still runs: the key moves one
    hand, the command file moves another, and the picture follows a third.
    """

    @pytest.mark.parametrize(
        "part", ["RobotHandState", "CruiseControlState", "ClipAdvanceState",
                 "RateLimitedTCodeSender"],
    )
    def test_the_module_builds_exactly_one_of_it(self, part):
        """Asked of the whole module rather than one function: a second one
        anywhere in here and the app still runs, with the key moving one hand
        while the picture follows another."""
        assert len(_calls(_module(), part)) == 1

    def test_the_sender_is_given_the_hand_it_was_built_beside(self):
        stack = _function("_build_drive_stack")

        assert _keyword(_call(stack, "RateLimitedTCodeSender"), "robot_hand") == "robot_hand"
        assert _keyword(_call(stack, "DriveStack"), "robot_hand") == "robot_hand"

    def test_every_part_of_the_app_is_given_that_same_stack(self):
        startup = _startup()

        assert len(_calls(startup, "_build_drive_stack")) == 1
        for named in ("robot_hand", "cruise_control_state", "clip_advance_state"):
            assert _keyword(_call(startup, "GenauControls"), named).startswith("drive.")
        assert _keyword(
            _call(startup, "GenauRefreshController"), "tcode_sender") == "drive.tcode_sender"

    def test_the_tick_is_driven_by_the_controls_that_were_built_here(self):
        """One object, so a command and a key move the same thing.  Build the
        tick its own and the two paths into every control drift apart silently."""
        startup = _startup()

        assert len(_calls(startup, "GenauControls")) == 1
        assert _keyword(_call(startup, "GenauRefreshController"), "controls") == "controls"


class TestWhichFileEachChannelIsGiven:
    def test_the_drive_readout_goes_where_fun_time_said(self):
        """The reader is Nau, told the path by Fun Time, so Genau has to be told
        the same one."""
        given = _keyword(_call(_startup(), "GenauRefreshController"), "drive_file")

        assert given == "Path(args.drive_file)"
