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
        started = _call(startup, "preload_thread.start")
        built = _call(startup, "PygameView")

        assert started.lineno < built.lineno

    def test_the_decode_is_waited_for_only_after_everything_else_is_wired(self):
        """The join is what makes the overlap worth having: move it up next to
        the start and the thread buys nothing at all."""
        startup = _startup()
        joined = _call(startup, "preload_thread.join")

        assert joined.lineno > _call(startup, "PygameView").lineno
        assert joined.lineno > _call(startup, "GenauRefreshController").lineno
        assert joined.lineno > _call(startup, "GenauLifecycleController").lineno

    def test_the_first_clip_is_put_on_screen_after_the_decode_is_waited_for(self):
        """Ahead of the join it would show the clip before its frames are in the
        cache, and the cache write would then land on a clip already up."""
        startup = _startup()

        assert (_call(startup, "selection.set_current_clip").lineno
                > _call(startup, "preload_thread.join").lineno)

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

        assert (_call(startup, "tcode_sender.close").lineno
                < _call(startup, "view.destroy").lineno)


class TestTheOneHandEveryPartIsGiven:
    """Genau has exactly one DirectControlState, and four parts move or read it.

    Build a second anywhere in here and the app still runs: the key moves one
    hand, the command file moves another, and the picture follows a third.
    """

    def test_only_one_hand_is_ever_built(self):
        assert len(_calls(_startup(), "DirectControlState")) == 1

    def test_the_sender_and_the_controls_are_given_that_same_hand(self):
        startup = _startup()

        assert _keyword(_call(startup, "RateLimitedTCodeSender"), "direct_state") == "direct_state"
        assert _keyword(_call(startup, "GenauControls"), "direct_state") == "direct_state"

    def test_the_tick_is_driven_by_the_controls_that_were_built_here(self):
        """One object, so a command and a key move the same thing.  Build the
        tick its own and the two paths into every control drift apart silently."""
        startup = _startup()

        assert len(_calls(startup, "GenauControls")) == 1
        assert _keyword(_call(startup, "GenauRefreshController"), "controls") == "controls"

    def test_only_one_cruise_stack_and_one_clip_advance_are_built(self):
        startup = _startup()

        assert len(_calls(startup, "CruiseControlState")) == 1
        assert len(_calls(startup, "ClipAdvanceState")) == 1


class TestWhichFileEachChannelIsGiven:
    def test_the_broker_is_told_who_owns_the_handoff(self):
        """Under Fun Time the orchestrator owns it and Genau must not also write
        PARK/RESUME; standalone there is nobody else to."""
        given = _keyword(_call(_startup(), "GenauRefreshController"), "broker_cmd_file")

        assert given == ("broker_cmd_file_for_mode(config.broker_cmd_file, "
                         "fun_time=args.fun_time)")

    def test_the_drive_readout_goes_where_the_launcher_said_or_to_our_own(self):
        """Under Fun Time the reader is Nau, told the path by Fun Time, so Genau
        has to be told the same one; standalone it is our own state dir."""
        given = _keyword(_call(_startup(), "GenauRefreshController"), "drive_file")

        assert given == ("Path(args.drive_file) if args.drive_file "
                         "else config.genau_drive_file")


class TestTheWindowIsToldWhoIsRunningIt:
    def test_it_is_borderless_only_under_an_orchestrator(self):
        """Fun Time owns the slot's geometry; standalone the window keeps its
        chrome so it can be moved and closed."""
        assert _keyword(_call(_startup(), "PygameView"), "borderless") == "args.fun_time"


class TestTheVoiceListener:
    def test_it_is_started_only_standalone_and_only_with_a_model(self):
        """Under Fun Time the orchestrator owns the microphone."""
        startup = _startup()
        guards = [_said(n.test) for n in ast.walk(startup)
                  if isinstance(n, ast.If) and "voice" in _said(n.test)]

        assert "config.voice is not None and (not args.fun_time)" in guards

    def test_it_writes_to_the_same_file_the_tick_drains(self):
        """Given anything else, every spoken command is written where nothing
        reads it and the feature is silently inert."""
        assert _keyword(_call(_startup(), "VoiceListener"), "cmd_file") == "command_file"
