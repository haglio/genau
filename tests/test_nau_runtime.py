from __future__ import annotations

import threading
from pathlib import Path

from nau.runtime import SEEK_STEP_MS, SPEED_STEP, apply_command
from nau.session import MAX_SPEED_RATE, MIN_SPEED_RATE


class SpySession:
    def __init__(self, loop_state: str = "normal") -> None:
        self.calls: list[tuple] = []
        self.loop_state = loop_state

    def step(self, delta: int) -> None:
        self.calls.append(("step", delta))

    def seek_by(self, delta_ms: float) -> None:
        self.calls.append(("seek_by", delta_ms))

    def record_down(self) -> None:
        self.calls.append(("record_down",))

    def record_up(self) -> None:
        self.calls.append(("record_up",))

    def loop_cancel(self) -> None:
        self.calls.append(("loop_cancel",))

    def cycle_version(self) -> None:
        self.calls.append(("cycle_version",))

    def play_file(self, video: Path, funscript: Path | None) -> None:
        self.calls.append(("play_file", video, funscript))

    def set_tcode_enabled(self, enabled: bool) -> None:
        self.calls.append(("set_tcode_enabled", enabled))

    def adjust_speed(self, delta: float) -> None:
        self.calls.append(("adjust_speed", delta))

    def set_speed(self, speed: float) -> None:
        self.calls.append(("set_speed", speed))


class TestApplyCommand:
    def test_next_and_prev_step(self):
        session = SpySession()

        assert apply_command("NEXT", session)
        assert apply_command("PREV", session)

        assert session.calls == [("step", 1), ("step", -1)]

    def test_keyword_is_case_insensitive(self):
        session = SpySession()

        assert apply_command("next", session)

        assert session.calls == [("step", 1)]

    def test_seek_commands(self):
        session = SpySession()

        apply_command("SEEK_FWD", session)
        apply_command("SEEK_BACK", session)

        assert session.calls == [
            ("seek_by", SEEK_STEP_MS), ("seek_by", -SEEK_STEP_MS),
        ]

    def test_speed_commands(self):
        session = SpySession()

        apply_command("SPEED_UP", session)
        apply_command("SPEED_DOWN", session)

        assert session.calls == [
            ("adjust_speed", SPEED_STEP), ("adjust_speed", -SPEED_STEP),
        ]

    def test_set_speed_absolute_and_extremes(self):
        session = SpySession()

        apply_command("SET_SPEED min", session)
        apply_command("SET_SPEED max", session)
        apply_command("SET_SPEED 1.5", session)

        assert session.calls == [
            ("set_speed", MIN_SPEED_RATE),
            ("set_speed", MAX_SPEED_RATE),
            ("set_speed", 1.5),
        ]

    def test_set_speed_without_or_invalid_argument_returns_false(self):
        session = SpySession()

        assert apply_command("SET_SPEED", session) is False
        assert apply_command("SET_SPEED fast", session) is False
        assert session.calls == []

    def test_record_commands(self):
        session = SpySession()

        apply_command("RECORD_DOWN", session)
        apply_command("RECORD_UP", session)
        apply_command("LOOP_CANCEL", session)

        assert session.calls == [("record_down",), ("record_up",), ("loop_cancel",)]

    def test_record_tap_cycles_by_state(self):
        normal = SpySession(loop_state="normal")
        apply_command("RECORD_TAP", normal)
        assert normal.calls == [("record_down",)]

        recording = SpySession(loop_state="recording")
        apply_command("RECORD_TAP", recording)
        assert recording.calls == [("record_up",)]

        looping = SpySession(loop_state="looping")
        apply_command("RECORD_TAP", looping)
        assert looping.calls == [("loop_cancel",)]

    def test_play_file_with_funscript(self):
        session = SpySession()

        apply_command(
            "PLAY_FILE C:/Videos/My Clip.mp4\tC:/Scripts/My Clip.funscript",
            session,
        )

        assert session.calls == [(
            "play_file",
            Path("C:/Videos/My Clip.mp4"),
            Path("C:/Scripts/My Clip.funscript"),
        )]

    def test_play_file_without_funscript(self):
        session = SpySession()

        apply_command("PLAY_FILE C:/Videos/My Clip.mp4", session)

        assert session.calls == [("play_file", Path("C:/Videos/My Clip.mp4"), None)]

    def test_cycle_version(self):
        session = SpySession()

        assert apply_command("CYCLE_VERSION", session)

        assert session.calls == [("cycle_version",)]

    def test_set_tcode_enabled_zero_disables(self):
        session = SpySession()

        assert apply_command("SET_TCODE_ENABLED 0", session)

        assert session.calls == [("set_tcode_enabled", False)]

    def test_set_tcode_enabled_one_enables(self):
        session = SpySession()

        assert apply_command("SET_TCODE_ENABLED 1", session)

        assert session.calls == [("set_tcode_enabled", True)]

    def test_set_tcode_enabled_without_argument_returns_false(self):
        session = SpySession()

        assert apply_command("SET_TCODE_ENABLED", session) is False
        assert session.calls == []

    def test_reload_playlist_invokes_callback(self):
        session = SpySession()
        reloaded = []

        apply_command("RELOAD_PLAYLIST", session, reload_playlist=lambda: reloaded.append(1))

        assert reloaded == [1]
        assert session.calls == []

    def test_toggle_length_mode_invokes_callback(self):
        session = SpySession()
        toggled = []

        assert apply_command(
            "TOGGLE_LENGTH_MODE", session,
            toggle_length_mode=lambda: toggled.append(1),
        )

        assert toggled == [1]
        assert session.calls == []

    def test_toggle_length_mode_without_callback_returns_false(self):
        session = SpySession()

        assert apply_command("TOGGLE_LENGTH_MODE", session) is False

    def test_set_length_mode_invokes_callback_with_mode(self):
        session = SpySession()
        modes = []

        assert apply_command(
            "SET_LENGTH_MODE shorts", session,
            set_length_mode=modes.append,
        )

        assert modes == ["shorts"]
        assert session.calls == []

    def test_set_length_mode_without_callback_returns_false(self):
        session = SpySession()

        assert apply_command("SET_LENGTH_MODE shorts", session) is False

    def test_set_length_mode_without_argument_returns_false(self):
        session = SpySession()

        assert apply_command(
            "SET_LENGTH_MODE", session, set_length_mode=lambda _m: None,
        ) is False

    def test_quit_sets_stop_event(self):
        session = SpySession()
        stop = threading.Event()

        apply_command("QUIT", session, stop_event=stop)

        assert stop.is_set()

    def test_unknown_command_returns_false(self):
        session = SpySession()

        assert apply_command("FROBNICATE", session) is False
        assert apply_command("", session) is False
        assert session.calls == []
