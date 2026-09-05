from __future__ import annotations

import threading
from pathlib import Path

import pytest

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


class TestAnUnhandledCommand:
    """The dispatcher says so itself, because it is the only thing that knows.

    Fun Time is written against this: `command_dispatch.py` routes
    CYCLE_PROJECTION and RECENTER to Nau's channel with the comment "so the
    desktop Nau simply logs it as unknown" -- verbs only FunTimeVR's player
    answers. Before this they were dropped in silence.
    """

    def test_an_unknown_verb_is_named_on_the_log(self, caplog):
        with caplog.at_level("WARNING", logger="nau.runtime"):
            apply_command("CYCLE_PROJECTION", SpySession())

        assert "CYCLE_PROJECTION" in caplog.text

    def test_a_verb_this_build_did_not_wire_is_named_too(self, caplog):
        """A collaborator the app left out is as unanswerable as a typo, and
        just as much worth seeing."""
        with caplog.at_level("WARNING", logger="nau.runtime"):
            apply_command("TOGGLE_LENGTH_MODE", SpySession())

        assert "TOGGLE_LENGTH_MODE" in caplog.text

    def test_the_one_verb_that_went_quiet_unwired_is_named_too(self, caplog):
        """RELOAD_PLAYLIST answered "handled" with its callback absent while
        the other eleven collaborator verbs answer False and get named here
        (bug 65)."""
        with caplog.at_level("WARNING", logger="nau.runtime"):
            apply_command("RELOAD_PLAYLIST", SpySession())

        assert "RELOAD_PLAYLIST" in caplog.text

    def test_a_verb_it_acts_on_says_nothing(self, caplog):
        with caplog.at_level("WARNING", logger="nau.runtime"):
            apply_command("NEXT", SpySession())

        assert caplog.records == []


class TestApplyCommand:
    def test_it_answers_nothing_because_nothing_asks(self):
        """nau/app.py, the one production caller, calls it as a statement.

        It used to return True/False for "did I understand this", and three
        helper docstrings promised a caller that reported an unhandled verb.
        There has never been one: an unknown or malformed verb is dropped in
        silence either way.
        """
        assert apply_command("NEXT", SpySession()) is None
        assert apply_command("NOT_A_VERB", SpySession()) is None

    def test_next_and_prev_step(self):
        session = SpySession()

        apply_command("NEXT", session)
        apply_command("PREV", session)

        assert session.calls == [("step", 1), ("step", -1)]

    def test_keyword_is_case_insensitive(self):
        session = SpySession()

        apply_command("next", session)

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

    def test_a_set_speed_it_cannot_read_leaves_the_rate_alone(self):
        session = SpySession()

        apply_command("SET_SPEED", session)
        apply_command("SET_SPEED fast", session)

        assert session.calls == []

    def test_set_volume_absolute(self):
        session = SpySession()

        apply_command("SET_VOLUME 40", session)

        assert session.calls == [("set_volume", 40)]

    def test_set_volume_without_or_invalid_argument_returns_false(self):
        session = SpySession()

        apply_command("SET_VOLUME", session) is False
        apply_command("SET_VOLUME loud", session) is False
        assert session.calls == []

    def test_set_volume_takes_the_mute_as_a_fact_of_its_own(self):
        """Fun Time publishes a mute to its audio sinks as a level of zero, which
        is all a sink needs and not enough to *draw*: silent and turned-all-the-way
        down look the same.  So the level and the mute both come, and the audible
        loudness is derived here."""
        session = SpySession()
        shown = []

        apply_command("SET_VOLUME 70 1", session, set_volume_hud=lambda *a: shown.append(a))

        assert session.calls == [("set_volume", 0)], "muted plays silent"
        assert shown == [(70, True)], "…but the control still shows where it was set"

    def test_set_volume_unmuted_plays_and_shows_the_same_level(self):
        session = SpySession()
        shown = []

        apply_command("SET_VOLUME 70 0", session, set_volume_hud=lambda *a: shown.append(a))

        assert session.calls == [("set_volume", 70)]
        assert shown == [(70, False)]

    def test_set_volume_without_a_mute_flag_is_not_muted(self):
        """The one-argument form is what every caller sent before there was a
        control to draw, and it means exactly what it did then."""
        session = SpySession()
        shown = []

        apply_command("SET_VOLUME 40", session, set_volume_hud=lambda *a: shown.append(a))

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

        apply_command("SET_LOOP 2000 4000", session)

        assert session.calls == [("restore_loop", 2000, 4000)]

    def test_a_set_loop_range_it_cannot_read_leaves_the_player_alone(self):
        session = SpySession()

        apply_command("SET_LOOP", session)
        apply_command("SET_LOOP 2000", session)
        apply_command("SET_LOOP 2000 later", session)

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

        apply_command("CYCLE_VERSION", session)

        assert session.calls == [("cycle_version",)]

    def test_set_tcode_enabled_zero_disables(self):
        session = SpySession()

        apply_command("SET_TCODE_ENABLED 0", session)

        assert session.calls == [("set_tcode_enabled", False)]

    def test_set_tcode_enabled_one_enables(self):
        session = SpySession()

        apply_command("SET_TCODE_ENABLED 1", session)

        assert session.calls == [("set_tcode_enabled", True)]

    def test_set_tcode_enabled_without_an_argument_leaves_the_driver_alone(self):
        session = SpySession()

        apply_command("SET_TCODE_ENABLED", session)

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

        apply_command(
            "TOGGLE_LENGTH_MODE", session,
            toggle_length_mode=lambda: toggled.append(1),
        )

        assert toggled == [1]
        assert session.calls == []

    def test_toggle_length_mode_without_its_callback_does_nothing(self):
        session = SpySession()

        apply_command("TOGGLE_LENGTH_MODE", session)

        assert session.calls == []

    def test_set_length_mode_invokes_callback_with_mode(self):
        session = SpySession()
        modes = []

        apply_command(
            "SET_LENGTH_MODE shorts", session,
            set_length_mode=modes.append,
        )

        assert modes == ["shorts"]
        assert session.calls == []

    def test_set_length_mode_without_its_callback_does_nothing(self):
        session = SpySession()

        apply_command("SET_LENGTH_MODE shorts", session)

        assert session.calls == []

    def test_set_length_mode_without_an_argument_does_not_call_back(self):
        modes: list[str] = []

        apply_command("SET_LENGTH_MODE", SpySession(), set_length_mode=modes.append)

        assert modes == []

    def test_end_compilation_invokes_callback(self):
        """Leaving a compilation without having to name a length: the mode you
        were in before you entered is the one you go back to."""
        session = SpySession()
        calls = []

        apply_command("END_COMPILATION", session, end_compilation=lambda: calls.append(1))

        assert calls == [1]
        assert session.calls == []

    def test_end_compilation_without_its_callback_does_nothing(self):
        session = SpySession()

        apply_command("END_COMPILATION", session)

        assert session.calls == []

    def test_set_f_mode_invokes_callback(self):
        """F-mode is Fun Time's flag; all Nau ever sees of it is a pre-narrowed
        playlist, which looks like any other.  So the orchestrator has to say it
        outright for the HUD to be able to."""
        session = SpySession()
        states = []

        apply_command("SET_F_MODE 1", session, set_f_mode=states.append)
        apply_command("SET_F_MODE 0", session, set_f_mode=states.append)

        assert states == [True, False]
        assert session.calls == []

    def test_set_f_mode_without_its_callback_or_its_argument_does_nothing(self):
        session = SpySession()
        flags: list[bool] = []

        apply_command("SET_F_MODE 1", session)
        apply_command("SET_F_MODE", session, set_f_mode=flags.append)

        assert (session.calls, flags) == ([], [])

    def test_display_verbs_invoke_callback(self):
        """Whether Nau owns the main slot's rect is Fun Time's to say: in genau mode
        it hands that rect to Genau and minimizes Nau, which keeps its taskbar
        button — so the player has to be told to go black rather than sit there
        holding the frame it was paused on."""
        session = SpySession()
        states = []

        apply_command("DISPLAY_OFF", session, set_display=states.append)
        apply_command("DISPLAY_ON", session, set_display=states.append)

        assert states == [False, True]
        assert session.calls == [], "the display is not playback"

    def test_display_verbs_without_their_callback_do_nothing(self):
        session = SpySession()

        apply_command("DISPLAY_OFF", session)
        apply_command("DISPLAY_ON", session)

        assert session.calls == []

    def test_quit_sets_stop_event(self):
        session = SpySession()
        stop = threading.Event()

        apply_command("QUIT", session, stop_event=stop)

        assert stop.is_set()

    def test_an_unknown_command_touches_nothing(self):
        session = SpySession()

        apply_command("FROBNICATE", session)
        apply_command("", session)

        assert session.calls == []


# Every command line Nau answers, one per verb, with fabricated arguments.
# Written out rather than read off the dispatcher: these strings are what Fun
# Time writes into nau_cmd.txt, so a verb renamed on this side is a control
# that goes quiet on the other, and the rename has to show up as a diff in both
# repos.  One-directional on purpose -- a verb ADDED here is backward
# compatible and this says nothing about it; a verb removed or respelled is
# what it catches.
ACCEPTED_COMMANDS = [
    "NEXT", "PREV", "SEEK_FWD", "SEEK_BACK",
    "SPEED_UP", "SPEED_DOWN", "SET_SPEED 1.5", "SET_SPEED min", "SET_SPEED max",
    "SET_VOLUME 40", "SET_VOLUME 40 1",
    "RECORD_DOWN", "RECORD_UP", "RECORD_TAP", "LOOP_CANCEL", "SET_LOOP 1000 2000",
    "TOGGLE_LOCK", "LOCK_ON", "LOCK_OFF",
    "CYCLE_VERSION", "PLAY_FILE C:/example/library/videos/gamma reel.mp4",
    "RELOAD_PLAYLIST", "TOGGLE_LENGTH_MODE", "SET_LENGTH_MODE shorts",
    "PLAY_COMPILATION", "PLAY_FULL_VID", "PLAY_CLIP_JUMP",
    "JUMP_TO_FUNSCRIPT", "NEXT_FUNSCRIPTED", "END_COMPILATION",
    "SET_TCODE_ENABLED 1", "SET_F_MODE 1",
    "DISPLAY_ON", "DISPLAY_OFF",
    "QUIT",
]

# The thirteen collaborators a fully wired player hands the dispatcher.
COLLABORATORS = (
    "reload_playlist", "toggle_length_mode", "set_length_mode", "play_compilation",
    "play_full_vid", "play_clip_jump", "jump_to_funscript", "next_funscripted",
    "end_compilation", "set_f_mode", "set_volume_hud", "set_display",
)


def _fully_wired() -> dict:
    return {name: (lambda *_args, **_kw: None) for name in COLLABORATORS} | {
        "stop_event": threading.Event()}


class TestTheVerbsFunTimeCanSend:
    """The command file is an orchestrator contract in the other direction from
    the status file: Fun Time writes these words and Nau acts on them.  The
    dispatcher says so itself -- an unhandled verb is a WARNING and nothing
    else -- so a respelled verb is a control that silently stops working, which
    is exactly what a log line nobody is reading looks like.
    """

    @pytest.mark.parametrize("command", ACCEPTED_COMMANDS)
    def test_it_is_answered_rather_than_logged_as_unknown(self, command, caplog):
        with caplog.at_level("WARNING", logger="nau.runtime"):
            apply_command(command, SpySession(), **_fully_wired())

        assert caplog.records == []

    def test_a_word_it_does_not_know_is_named_on_the_log(self, caplog):
        """The control probe: without it, a dispatcher that answered everything
        would pass every case above."""
        with caplog.at_level("WARNING", logger="nau.runtime"):
            apply_command("FROBNICATE", SpySession(), **_fully_wired())

        assert "FROBNICATE" in caplog.text
