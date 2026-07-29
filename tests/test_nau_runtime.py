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

    def restore_loop(self, in_ms: int, out_ms: int) -> None:
        self.calls.append(("restore_loop", in_ms, out_ms))

    def toggle_lock(self) -> None:
        self.calls.append(("toggle_lock",))

    def set_locked(self, locked: bool) -> None:
        self.calls.append(("set_locked", locked))

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

    def set_volume(self, volume: int) -> None:
        self.calls.append(("set_volume", volume))


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

    def test_set_volume_absolute(self):
        session = SpySession()

        assert apply_command("SET_VOLUME 40", session)

        assert session.calls == [("set_volume", 40)]

    def test_set_volume_without_or_invalid_argument_returns_false(self):
        session = SpySession()

        assert apply_command("SET_VOLUME", session) is False
        assert apply_command("SET_VOLUME loud", session) is False
        assert session.calls == []

    def test_set_volume_takes_the_mute_as_a_fact_of_its_own(self):
        """Fun Time publishes a mute to its audio sinks as a level of zero, which
        is all a sink needs and not enough to *draw*: silent and turned-all-the-way
        down look the same.  So the level and the mute both come, and the audible
        loudness is derived here."""
        session = SpySession()
        shown = []

        assert apply_command("SET_VOLUME 70 1", session, set_volume_hud=lambda *a: shown.append(a))

        assert session.calls == [("set_volume", 0)], "muted plays silent"
        assert shown == [(70, True)], "…but the control still shows where it was set"

    def test_set_volume_unmuted_plays_and_shows_the_same_level(self):
        session = SpySession()
        shown = []

        assert apply_command("SET_VOLUME 70 0", session, set_volume_hud=lambda *a: shown.append(a))

        assert session.calls == [("set_volume", 70)]
        assert shown == [(70, False)]

    def test_set_volume_without_a_mute_flag_is_not_muted(self):
        """The one-argument form is what every caller sent before there was a
        control to draw, and it means exactly what it did then."""
        session = SpySession()
        shown = []

        assert apply_command("SET_VOLUME 40", session, set_volume_hud=lambda *a: shown.append(a))

        assert session.calls == [("set_volume", 40)]
        assert shown == [(40, False)]

    def test_record_commands(self):
        session = SpySession()

        apply_command("RECORD_DOWN", session)
        apply_command("RECORD_UP", session)
        apply_command("LOOP_CANCEL", session)

        assert session.calls == [("record_down",), ("record_up",), ("loop_cancel",)]

    def test_set_loop_puts_a_range_back_without_replaying_the_gesture(self):
        """How a loop survives a restart: Fun Time reads the bounds off the
        status file, and hands them back over the video it resumed the playlist
        onto — RECORD_DOWN/RECORD_UP could not, since they mark against wherever
        the playhead happens to be."""
        session = SpySession()

        assert apply_command("SET_LOOP 2000 4000", session)

        assert session.calls == [("restore_loop", 2000, 4000)]

    def test_set_loop_reports_a_range_it_cannot_read_as_unhandled(self):
        session = SpySession()

        assert apply_command("SET_LOOP", session) is False
        assert apply_command("SET_LOOP 2000", session) is False
        assert apply_command("SET_LOOP 2000 later", session) is False
        assert session.calls == []

    def test_lock_commands(self):
        """The toggle for the key and the button; the absolute pair for the two
        spoken forms, which name the state they want."""
        session = SpySession()

        apply_command("TOGGLE_LOCK", session)
        apply_command("LOCK_ON", session)
        apply_command("LOCK_OFF", session)

        assert session.calls == [
            ("toggle_lock",), ("set_locked", True), ("set_locked", False),
        ]

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

    def test_end_compilation_invokes_callback(self):
        """Leaving a compilation without having to name a length: the mode you
        were in before you entered is the one you go back to."""
        session = SpySession()
        calls = []

        assert apply_command("END_COMPILATION", session, end_compilation=lambda: calls.append(1))

        assert calls == [1]
        assert session.calls == []

    def test_end_compilation_without_callback_returns_false(self):
        assert apply_command("END_COMPILATION", SpySession()) is False

    def test_set_f_mode_invokes_callback(self):
        """F-mode is Fun Time's flag; all Nau ever sees of it is a pre-narrowed
        playlist, which looks like any other.  So the orchestrator has to say it
        outright for the HUD to be able to."""
        session = SpySession()
        states = []

        assert apply_command("SET_F_MODE 1", session, set_f_mode=states.append)
        assert apply_command("SET_F_MODE 0", session, set_f_mode=states.append)

        assert states == [True, False]
        assert session.calls == []

    def test_set_f_mode_without_callback_or_argument_returns_false(self):
        session = SpySession()

        assert apply_command("SET_F_MODE 1", session) is False
        assert apply_command("SET_F_MODE", session, set_f_mode=lambda _f: None) is False

    def test_display_verbs_invoke_callback(self):
        """Whether Nau owns the main slot's rect is Fun Time's to say: in genau mode
        it hands that rect to Genau and minimizes Nau, which keeps its taskbar
        button — so the player has to be told to go black rather than sit there
        holding the frame it was paused on."""
        session = SpySession()
        states = []

        assert apply_command("DISPLAY_OFF", session, set_display=states.append)
        assert apply_command("DISPLAY_ON", session, set_display=states.append)

        assert states == [False, True]
        assert session.calls == [], "the display is not playback"

    def test_display_verbs_without_callback_return_false(self):
        session = SpySession()

        assert apply_command("DISPLAY_OFF", session) is False
        assert apply_command("DISPLAY_ON", session) is False

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
