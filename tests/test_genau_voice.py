"""Tests for genau.voice."""
from __future__ import annotations

import json

from genau.voice import (
    VOICE_COMMANDS,
    VoiceListener,
    build_grammar,
    parse_vosk_result,
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

    def test_all_values_are_recognized_runtime_commands(self):
        valid_static = {
            "PAUSE", "RESUME", "SPEED_DOWN", "SPEED_UP",
            "AMPLITUDE_DOWN", "AMPLITUDE_UP",
            "CENTER_DOWN", "CENTER_UP",
            "CYCLE_SHAPE", "TOGGLE_CRUISE", "PREV", "NEXT",
        }
        numeric_prefixes = ("AMP ", "CENTER ", "SPEED ")
        for phrase, cmd in VOICE_COMMANDS.items():
            if any(cmd.startswith(p) for p in numeric_prefixes):
                _, value = cmd.split(" ", 1)
                assert value.isdigit(), f"'{phrase}' has non-integer value '{value}'"
            else:
                assert cmd in valid_static, f"'{phrase}' maps to unknown command '{cmd}'"

    def test_contains_expected_phrases(self):
        expected = {
            "pause", "play", "resume",
            "slow down", "speed down", "speed up",
            "amp down", "amp up",
            "center down", "center up",
            "cycle shape", "genau auto",
            "previous clip", "next clip",
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

    def test_stop_sets_event(self):
        listener = VoiceListener(
            commands={},
            cmd_file="dummy",
            model_path="dummy",
        )

        listener.stop()

        assert listener._stop.is_set()


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
