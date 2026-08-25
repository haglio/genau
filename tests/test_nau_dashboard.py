from __future__ import annotations

import threading
from pathlib import Path

from genau.session_quit import SESSION_QUIT
from nau.dashboard import Dashboard


class TestAskingForSomething:
    def test_the_ask_goes_out_on_the_dashboards_channel(self, tmp_path: Path):
        dashboard = Dashboard(tmp_path / "dashboard_cmd.txt")

        dashboard.post("audio_mute")

        assert (tmp_path / "dashboard_cmd.txt").read_text(
            encoding="utf-8").split() == ["audio_mute"]

    def test_a_second_ask_joins_the_queue_rather_than_replacing_it(self, tmp_path: Path):
        """That file carries every mouse- and voice-driven writer at once and
        the dispatch loop drains it a tick at a time, so an ask that overwrote
        it would drop whatever was still waiting."""
        dashboard = Dashboard(tmp_path / "dashboard_cmd.txt")

        dashboard.post("main_next")
        dashboard.post("audio_set_volume|40")

        assert (tmp_path / "dashboard_cmd.txt").read_text(encoding="utf-8").split() == [
            "main_next", "audio_set_volume|40"]

    def test_standalone_there_is_nowhere_to_ask_and_the_control_is_inert(self):
        """Every control on this HUD asks rather than acts, so with no Fun Time
        behind it a press does nothing at all -- and the control goes on showing
        whatever is actually the case rather than pretending it moved."""
        Dashboard(None).post("audio_mute")  # no file, and no exception either


class TestAQuitGesture:
    """The close box, Alt+F4, Ctrl+Q -- every way this window is told to go."""

    def test_in_a_session_it_asks_and_this_player_keeps_running(self, tmp_path: Path):
        """Nau stays up until the teardown reaches it, so the closing cover is
        what the user watches rather than the main slot emptying ahead of
        everything else."""
        cmd_file = tmp_path / "dashboard_cmd.txt"
        stop_event = threading.Event()

        Dashboard(cmd_file).take_quit_gesture(stop_event)

        assert cmd_file.read_text(encoding="utf-8").split() == [SESSION_QUIT]
        assert not stop_event.is_set()

    def test_standalone_the_gesture_stops_this_player(self):
        """No dashboard is what standalone means: there is nobody to ask, and
        closing the window is exactly what the user asked for."""
        stop_event = threading.Event()

        Dashboard(None).take_quit_gesture(stop_event)

        assert stop_event.is_set()
