"""Tests for genau.voice."""
from __future__ import annotations

import json
import threading

import pytest

from player_core.cruise_control import CruiseControlState
from player_core.direct_control import DirectControlState

from genau.clip_advance import ClipAdvanceState
from genau.engine import PlaybackEngine
from genau.flags import Flag
from genau.controls import GenauControls
from genau.runtime_commands import apply_runtime_command
from genau.voice import (
    VOICE_COMMANDS,
    VoiceListener,
    build_grammar,
    parse_vosk_result,
)


def _collaborators() -> dict:
    """Everything the dispatcher can be handed, so no verb is refused for want
    of one — which would read as an unhandled verb and hide a real gap."""
    return dict(
        engine=PlaybackEngine(phase=0.0, last_tick=0.0),
        paused=Flag(),
        step_clip=lambda _step: None,
        discard_clip=lambda: None,
        direct_state=DirectControlState(playing=True),
        cruise_control_state=CruiseControlState(),
        set_stroke_phase=lambda _phase: None,
        clip_advance_state=ClipAdvanceState(),
        stop_event=threading.Event(),
        hud=Flag(),
        display=Flag(),
        set_volume=lambda *_a: None,
        reorder_clips=lambda *_a, **_k: None,
    )


class TestBuildGrammar:
    def test_returns_sorted_phrases_with_unk(self):
        commands = {"hello": "CMD_A", "apple": "CMD_B"}

        result = json.loads(build_grammar(commands))

        assert result == ["apple", "hello", "[unk]"]

    def test_empty_commands_returns_only_unk(self):
        result = json.loads(build_grammar({}))

        assert result == ["[unk]"]


class TestParseVoskResult:
    def test_recognized_phrase_returns_command(self):
        commands = {"speed up": "SPEED_UP", "slow down": "SPEED_DOWN"}
        raw = json.dumps({"text": "speed up"})

        result = parse_vosk_result(raw, commands, threshold=0.7)

        assert result == "SPEED_UP"

    def test_empty_text_returns_none(self):
        commands = {"speed up": "SPEED_UP"}
        raw = json.dumps({"text": ""})

        assert parse_vosk_result(raw, commands, threshold=0.7) is None

    def test_unk_text_returns_none(self):
        commands = {"speed up": "SPEED_UP"}
        raw = json.dumps({"text": "[unk]"})

        assert parse_vosk_result(raw, commands, threshold=0.7) is None

    def test_unrecognized_phrase_returns_none(self):
        commands = {"speed up": "SPEED_UP"}
        raw = json.dumps({"text": "something else"})

        assert parse_vosk_result(raw, commands, threshold=0.7) is None

    def test_low_confidence_returns_none(self):
        commands = {"speed up": "SPEED_UP"}
        raw = json.dumps({
            "text": "speed up",
            "result": [{"word": "speed", "conf": 0.3}, {"word": "up", "conf": 0.4}],
        })

        assert parse_vosk_result(raw, commands, threshold=0.7) is None

    def test_high_confidence_returns_command(self):
        commands = {"speed up": "SPEED_UP"}
        raw = json.dumps({
            "text": "speed up",
            "result": [{"word": "speed", "conf": 0.9}, {"word": "up", "conf": 0.8}],
        })

        assert parse_vosk_result(raw, commands, threshold=0.7) == "SPEED_UP"

    def test_missing_confidence_data_accepts_phrase(self):
        commands = {"speed up": "SPEED_UP"}
        raw = json.dumps({"text": "speed up"})

        assert parse_vosk_result(raw, commands, threshold=0.7) == "SPEED_UP"


class TestVoiceCommands:
    def test_slow_down_maps_to_speed_down(self):
        assert VOICE_COMMANDS["slow down"] == "SPEED_DOWN"

    def test_speed_down_maps_to_speed_down(self):
        assert VOICE_COMMANDS["speed down"] == "SPEED_DOWN"

    @pytest.mark.parametrize("phrase, verb", sorted(VOICE_COMMANDS.items()))
    def test_every_spoken_phrase_names_a_verb_the_runtime_handles(self, phrase, verb, caplog):
        """The contract, asked of the dispatcher rather than of a list.

        The allowlist this replaces was fifteen names typed into the test: it
        answered "is this one of the fifteen I wrote down", which a renamed
        branch passes and a speaker does not.  Asked of the log, because that
        is where the dispatcher now puts a verb it cannot answer and the only
        place production can see one.
        """
        with caplog.at_level("WARNING", logger="genau.runtime_commands"):
            apply_runtime_command(verb, GenauControls(**_collaborators()))

        assert caplog.records == [], (
            f"{phrase!r} says {verb!r}, which nothing handles")

    def test_quit_maps_to_quit_command(self):
        assert VOICE_COMMANDS["quit"] == "QUIT"

    def test_contains_expected_phrases(self):
        expected = {
            "pause", "play", "resume",
            "slow down", "speed down", "speed up",
            "amp down", "amp up",
            "center down", "center up",
            "cycle shape", "cruise control", "cruise on", "cruise off",
            "previous clip", "next clip",
            "quit",
        }
        assert expected <= set(VOICE_COMMANDS.keys())

    def test_amp_fifty_maps_to_numeric_command(self):
        assert VOICE_COMMANDS["amp fifty"] == "AMP 50"

    def test_center_eighty_maps_to_numeric_command(self):
        assert VOICE_COMMANDS["center eighty"] == "CENTER 80"

    def test_speed_thirty_maps_to_numeric_command(self):
        assert VOICE_COMMANDS["speed thirty"] == "SPEED 30"

    def test_amp_zero_and_one_hundred(self):
        assert VOICE_COMMANDS["amp zero"] == "AMP 0"
        assert VOICE_COMMANDS["amp one hundred"] == "AMP 100"


class TestVoiceListener:
    def test_write_command_writes_to_file(self, tmp_path):
        cmd_file = tmp_path / "genau_cmd.txt"
        listener = VoiceListener(
            commands={"test": "TEST_CMD"},
            cmd_file=cmd_file,
            model_path="dummy",
        )

        listener._write_command("TEST_CMD")

        assert cmd_file.read_text(encoding="utf-8") == "TEST_CMD"

    def test_the_listener_has_no_stop_handle(self):
        """Nothing can stop it, and that is the design.

        genau/app.py builds the listener into a local, hands ``run`` to a
        daemon thread and drops the reference, so the loop ends when the
        process does. A ``stop()`` only a test could reach read as an orderly
        shutdown that has never existed -- and the vulture whitelist asserted
        it was "called externally to signal shutdown", which was false.
        """
        assert not hasattr(VoiceListener, "stop")


class TestFunTimeFlag:
    def test_parser_accepts_fun_time(self, cfg_path):
        from genau.app import build_parser
        from genau.config import load_config
        config = load_config(cfg_path)
        parser = build_parser(config)

        args = parser.parse_args(["--fun-time"])

        assert args.fun_time is True

    def test_parser_defaults_fun_time_to_false(self, cfg_path):
        from genau.app import build_parser
        from genau.config import load_config
        config = load_config(cfg_path)
        parser = build_parser(config)

        args = parser.parse_args([])

        assert args.fun_time is False


class TestStartClip:
    """Where a reopened session picks Genau up: the clip it was left showing,
    named on the command line rather than sent as a verb — the command channel
    upper-cases every line it reads, which a path cannot survive, and a verb
    would arrive after the wrong clip had already been decoded."""

    def test_parser_takes_the_clip_to_open_on(self, cfg_path):
        from genau.app import build_parser
        from genau.config import load_config
        parser = build_parser(load_config(cfg_path))

        args = parser.parse_args(["--start-clip", "C:/clips/alpha.mp4"])

        assert args.start_clip == "C:/clips/alpha.mp4"

    def test_parser_defaults_to_no_named_clip(self, cfg_path):
        from genau.app import build_parser
        from genau.config import load_config
        parser = build_parser(load_config(cfg_path))

        assert parser.parse_args([]).start_clip is None
