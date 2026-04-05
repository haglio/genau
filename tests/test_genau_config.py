"""Tests for genau.config."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from genau.config import ProjectConfig, VoiceConfig, load_config


class TestLoadConfig:
    def test_loads_valid_config(self, cfg_path: Path):
        cfg = load_config(cfg_path)
        assert isinstance(cfg, ProjectConfig)

    def test_raises_on_missing_file(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nonexistent.json")

    def test_raises_on_missing_genau_section(self, tmp_path: Path):
        cfg_file = tmp_path / "bad.json"
        cfg_file.write_text(json.dumps({"clips_dir": "x", "state_dir": "y"}), encoding="utf-8")
        with pytest.raises(ValueError, match="genau"):
            load_config(cfg_file)

    def test_loads_clips_dir(self, cfg_path: Path, tmp_path: Path):
        cfg = load_config(cfg_path)
        assert cfg.clips_dir == tmp_path / "clips"

    def test_loads_genau_settings(self, cfg_path: Path):
        cfg = load_config(cfg_path)
        assert cfg.genau.beats_per_loop == 1.0
        assert cfg.genau.clip_cache_size == 2
        assert cfg.genau.shuffle_on_load is True
        assert cfg.genau.udp_port == 50555

    def test_genau_cmd_file(self, cfg_path: Path, tmp_path: Path):
        cfg = load_config(cfg_path)
        assert cfg.genau_cmd_file == tmp_path / "state" / "genau_cmd.txt"

    def test_genau_paused_file(self, cfg_path: Path, tmp_path: Path):
        cfg = load_config(cfg_path)
        assert cfg.genau_paused_file == tmp_path / "state" / "genau_paused.txt"

    def test_log_file(self, cfg_path: Path, tmp_path: Path):
        cfg = load_config(cfg_path)
        assert cfg.log_file("genau_listener") == tmp_path / "state" / "genau_listener.log"

    def test_logs_dir(self, cfg_path: Path, tmp_path: Path):
        cfg = load_config(cfg_path)
        assert cfg.logs_dir == tmp_path / "state"

    def test_broker_tray_launcher_defaults_to_none(self, cfg_path: Path):
        cfg = load_config(cfg_path)
        assert cfg.broker_tray_launcher is None

    def test_loads_broker_tray_launcher(self, tmp_path: Path):
        vbs = tmp_path / "launch_broker_tray.vbs"
        vbs.touch()
        cfg_file = tmp_path / "genau_config.json"
        cfg_file.write_text(json.dumps({
            "clips_dir": str(tmp_path / "clips"),
            "state_dir": "state",
            "broker_tray_launcher": str(vbs),
            "genau": {
                "shuffle_on_load": True,
                "beats_per_loop": 1.0,
                "clip_cache_size": 2,
                "render_batch": 6,
                "bpm_smoothing": 0.14,
                "sync_strength": 0.35,
                "udp_host": "127.0.0.1",
                "udp_port": 50555,
                "notify_host": "127.0.0.1",
                "notify_port": 50556,
                "resize_debounce_ms": 120,
                "tcode_udp_host": "127.0.0.1",
                "tcode_udp_port": 50557,
            },
        }), encoding="utf-8")
        (tmp_path / "state").mkdir(exist_ok=True)
        (tmp_path / "clips").mkdir(exist_ok=True)
        cfg = load_config(cfg_file)
        assert cfg.broker_tray_launcher == vbs

    def test_relative_state_dir_resolved_against_project_dir(self, tmp_path: Path):
        cfg_file = tmp_path / "genau_config.json"
        cfg_file.write_text(json.dumps({
            "clips_dir": str(tmp_path / "clips"),
            "state_dir": "state",
            "genau": {
                "shuffle_on_load": True,
                "beats_per_loop": 1.0,
                "clip_cache_size": 2,
                "render_batch": 6,
                "bpm_smoothing": 0.14,
                "sync_strength": 0.35,
                "udp_host": "127.0.0.1",
                "udp_port": 50555,
                "notify_host": "127.0.0.1",
                "notify_port": 50556,
                "resize_debounce_ms": 120,
                "tcode_udp_host": "127.0.0.1",
                "tcode_udp_port": 50557,
            },
        }), encoding="utf-8")
        cfg = load_config(cfg_file)
        # Relative state_dir resolves against the config file's parent directory
        assert cfg.state_dir.is_absolute()

    def test_voice_defaults_to_none_when_absent(self, cfg_path: Path):
        cfg = load_config(cfg_path)
        assert cfg.voice is None

    def test_voice_loaded_when_present(self, cfg_factory):
        cfg_path = cfg_factory({
            "voice_control": {
                "model_path": "vosk-model-small-en-us-0.15",
                "device_index": 2,
            },
        })
        cfg = load_config(cfg_path)
        assert isinstance(cfg.voice, VoiceConfig)
        assert cfg.voice.model_path == "vosk-model-small-en-us-0.15"
        assert cfg.voice.device_index == 2
        assert cfg.voice.confidence_threshold == 0.7
        assert cfg.voice.sample_rate == 16000
