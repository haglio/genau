"""The shared config, as GenauVR reads it.

It read the same genau_config.json Genau does into a bare dict and dug each key
out at the point of use, with an inline default beside it -- so a mistyped key
was a silent default, a relative path was resolved against whatever directory
the shortcut started in, and two settings that exist in the file were hardcoded
at the call site instead of read.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from genau_vr.config import (
    DEFAULT_TCODE_HOST,
    DEFAULT_TCODE_PORT,
    VrConfig,
    clips_to_play,
    load_config,
)


def _written(tmp_path: Path, **keys) -> Path:
    path = tmp_path / "genau_config.json"
    path.write_text(json.dumps(keys), encoding="utf-8")
    return path


class TestWhatItReads:
    def test_the_tcode_endpoint_comes_out_of_the_genau_section(self, tmp_path):
        config = load_config(_written(
            tmp_path, state_dir="state",
            genau={"tcode_udp_host": "10.0.0.4", "tcode_udp_port": 50999},
        ))

        assert config.tcode_endpoint == ("10.0.0.4", 50999)

    def test_a_config_with_no_tcode_section_names_the_family_endpoint(self, tmp_path):
        config = load_config(_written(tmp_path, state_dir="state"))

        assert config.tcode_endpoint == (DEFAULT_TCODE_HOST, DEFAULT_TCODE_PORT)

    def test_the_voice_block_comes_across_whole(self, tmp_path):
        config = load_config(_written(tmp_path, state_dir="state", voice_control={
            "model_path": "example-model", "confidence_threshold": 0.9,
            "device_index": 3, "sample_rate": 48000,
        }))

        assert (config.voice.model_path, config.voice.confidence_threshold,
                config.voice.device_index, config.voice.sample_rate) == (
            "example-model", 0.9, 3, 48000)

    def test_a_config_with_no_voice_block_still_has_a_model_to_ask_for(self, tmp_path):
        config = load_config(_written(tmp_path, state_dir="state"))

        assert config.voice.model_path
        assert config.voice.device_index is None


class TestWhereARelativePathIsRelativeTo:
    """The config, not the directory the shortcut happened to start us in --
    which under pythonw is not the folder anyone would guess."""

    def test_the_state_directory_lands_beside_the_config(self, tmp_path):
        config = load_config(_written(tmp_path, state_dir="state"))

        assert config.state_dir == tmp_path / "state"

    def test_it_is_made_rather_than_assumed(self, tmp_path):
        config = load_config(_written(tmp_path, state_dir="state"))

        assert config.state_dir.is_dir()

    def test_an_absolute_path_is_left_alone(self, tmp_path):
        elsewhere = tmp_path / "elsewhere"
        config = load_config(_written(tmp_path, state_dir=str(elsewhere)))

        assert config.state_dir == elsewhere

    def test_a_relative_clips_folder_lands_beside_the_config_too(self, tmp_path):
        config = load_config(_written(tmp_path, state_dir="state", vr_clips_dir="vr"))

        assert config.vr_clips_dir == tmp_path / "vr"


class TestAConfigItCannotRead:
    """The shortcut launches GenauVR hidden, so a startup that stops has to
    stop somewhere that can explain itself.  A config that is missing or
    unreadable takes its defaults and says so on the log; what stops the run is
    the *clips*, which is the thing actually missing and the message that names
    it."""

    def test_an_absent_file_takes_the_defaults_and_says_so(self, tmp_path, caplog):
        with caplog.at_level("WARNING", logger="genau_vr.config"):
            config = load_config(tmp_path / "not-here.json")

        assert config.tcode_endpoint == (DEFAULT_TCODE_HOST, DEFAULT_TCODE_PORT)
        assert "not-here.json" in caplog.text

    def test_a_file_that_is_not_json_does_the_same(self, tmp_path, caplog):
        path = tmp_path / "genau_config.json"
        path.write_text("{not json", encoding="utf-8")

        with caplog.at_level("WARNING", logger="genau_vr.config"):
            config = load_config(path)

        assert config.tcode_endpoint == (DEFAULT_TCODE_HOST, DEFAULT_TCODE_PORT)
        assert "genau_config.json" in caplog.text

    def test_and_the_run_still_stops_on_the_clips(self, tmp_path):
        config = load_config(tmp_path / "not-here.json")

        with pytest.raises(RuntimeError):
            clips_to_play(None, config)


def test_a_config_carries_no_state_beyond_what_it_was_read_from(tmp_path):
    """Frozen, because five call sites used to be handed the dict and any of
    them could have written to it."""
    config = VrConfig(state_dir=tmp_path)

    with pytest.raises(Exception):
        config.tcode_port = 1
