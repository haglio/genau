"""Nau's own module: what it wires together before the loop starts.

``nau.app`` is imported inside each test rather than at module scope: importing
it pulls pygame in for real, and the view tests that replace pygame with a mock
go red inside pygame's own resource lookup if that happens before they run.  By
the time these do, those have.  ``tests/test_taskbar_identity.py`` reaches its
two names the same way and says the same thing.
"""
from __future__ import annotations

import logging
from pathlib import Path

from nau.cli import build_parser


class StubSession:
    """The shape :func:`nau.status.status_fields` reads a player through."""

    current_video = Path("C:/vids/gamma reel.mp4")
    position_ms = 12345.6
    duration_ms = 60000.0
    has_funscript = True
    funscript_resting = False
    loop_state = "normal"
    loop_bounds = None
    is_paused = False
    locked = True


class FakeGate:
    """The trace's latch, as the status file asks it: one touch, or none."""

    def __init__(self, touch: int | None = None) -> None:
        self.touch = touch
        self.asked = 0

    def handoff_touch(self) -> int | None:
        self.asked += 1
        return self.touch


def _writer(args, gate):
    from nau.app import _status_writer
    return _status_writer(args, gate)


def _args(status_file: Path | None):
    argv = [] if status_file is None else ["--status-file", str(status_file)]
    return build_parser({}).parse_args(argv)


class TestTheStatusFileNauPublishes:
    """The reverse leg of the orchestrator channel: fun_time polls this file to
    know what this player is showing.  What goes in it is
    :func:`nau.status.status_fields`, which is pinned key by key in
    tests/test_nau_status.py; what is pinned here is the wiring between that and
    the file -- the part a loop-splitting change can quietly drop, leaving the
    whole suite green while the field it stopped filling publishes empty.
    """

    def test_a_status_carries_the_touch_the_trace_had_chosen_by_then(self, tmp_path):
        """Asked of the gate as the status is written, not captured when the
        writer is built: the choice is made while the frame is painted, and the
        writer publishes at its own throttled cadence in between."""
        status = tmp_path / "nau_status.txt"
        gate = FakeGate()
        writer = _writer(_args(status), gate)

        gate.touch = 4200          # chosen later, while a frame was painted
        writer.write(StubSession())

        assert "handoff_touch_ms=4200" in status.read_text(encoding="utf-8")

    def test_no_touch_chosen_yet_publishes_the_empty_field(self, tmp_path):
        """Zero is a real media time; an arbiter reading one would end Genau's
        turn at the top of the video."""
        status = tmp_path / "nau_status.txt"
        writer = _writer(_args(status), FakeGate(None))

        writer.write(StubSession())

        assert "handoff_touch_ms=\n" in status.read_text(encoding="utf-8")

    def test_a_player_nobody_asked_for_a_status_from_publishes_nothing(self):
        """Standalone there is no orchestrator polling, and no file to write."""
        assert _writer(_args(None), FakeGate(4200)) is None

    def test_the_gate_is_not_asked_at_all_when_there_is_no_file(self):
        gate = FakeGate(4200)

        _writer(_args(None), gate)

        assert gate.asked == 0


class TestWhenSomethingCosmeticFails:
    """Three things Nau does on the way in are decoration -- its window icon,
    the name it leaves for the task list, the taskbar button it claims -- and
    every one of them catches everything, because none of them may cost a
    launch.  Caught silently, though, a permanently broken one is
    indistinguishable in the log from one that works.
    """

    def test_an_icon_it_cannot_read_is_said_rather_than_swallowed(
        self, tmp_path, caplog, monkeypatch,
    ):
        import nau.app as app
        not_an_icon = tmp_path / "nau_icon.ico"
        not_an_icon.write_text("this is not an icon", encoding="utf-8")
        monkeypatch.setattr(app, "_ICON_PATH", not_an_icon)

        with caplog.at_level(logging.DEBUG, logger="nau.app"):
            surface = app._load_icon_surface()

        assert surface is None
        assert "icon" in caplog.text.lower()


class TestWhichConfigTheFlagsAreReadAgainst:
    """Nau parses twice on purpose.  The first pass exists only to find out
    whether ``--config`` names a file other than the default one; if it does,
    the parser is built again from THAT file, because every default it feeds --
    the library directories, the state dir, the device's port -- would
    otherwise come from a config this run was told not to use.
    """

    def _main(self, monkeypatch, argv):
        import nau.app as app
        landed = []
        monkeypatch.setattr(app, "_name_this_process", lambda: None)
        monkeypatch.setattr(app, "_run", lambda args: landed.append(args) or 0)
        app.main(argv)
        return landed[0]

    def test_a_named_config_supplies_the_defaults(self, tmp_path, monkeypatch):
        config = tmp_path / "genau_config.json"
        config.write_text('{"nau": {"tcode_udp_port": 51000}}', encoding="utf-8")

        args = self._main(monkeypatch, ["--config", str(config)])

        assert args.tcode_port == 51000

    def test_a_flag_still_beats_the_config_it_named(self, tmp_path, monkeypatch):
        """The whole line is parsed again, not patched, so the flags keep
        winning -- which they would not if the second pass only filled gaps."""
        config = tmp_path / "genau_config.json"
        config.write_text('{"nau": {"tcode_udp_port": 51000}}', encoding="utf-8")

        args = self._main(
            monkeypatch, ["--config", str(config), "--tcode-port", "50999"])

        assert args.tcode_port == 50999
