"""Configuration loader for Genau."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app_support.config_reader import (
    read_json_config,
    require_path,
    require_section,
    require_typed,
)
from app_support.state_files import GENAU_CMD, GENAU_DRIVE, GENAU_PAUSED

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_DIR / "genau_config.json"


# The files of the orchestrator channel this window is told about are named
# once for the family, in app_support.state_files, beside who writes and who
# reads each; the fourth, the status file, is read from there by the engine
# that writes it (player_core.genau_status).


@dataclass(frozen=True)
class GenauConfig:
    shuffle_on_load: bool
    beats_per_loop: float
    clip_cache_size: int
    bpm_smoothing: float
    sync_strength: float
    udp_host: str
    udp_port: int
    notify_host: str
    notify_port: int
    resize_debounce_ms: int
    tcode_udp_host: str
    tcode_udp_port: int


@dataclass(frozen=True)
class ProjectConfig:
    clips_dir: Path
    state_dir: Path
    genau: GenauConfig

    @property
    def genau_cmd_file(self) -> Path:
        return self.state_dir / GENAU_CMD

    @property
    def genau_paused_file(self) -> Path:
        return self.state_dir / GENAU_PAUSED

    @property
    def genau_drive_file(self) -> Path:
        """Where Genau says what it is driving the device with, for Nau to draw.

        In video mode the readout belongs to Nau's console — the controls that move
        these numbers are on it — so Genau publishes rather than paints.
        """
        return self.state_dir / GENAU_DRIVE

    @property
    def logs_dir(self) -> Path:
        return self.state_dir

    def log_file(self, name: str) -> Path:
        return self.logs_dir / f"{name}.log"


def load_config(config_path: str | Path | None = None) -> ProjectConfig:
    # Every required key is asked for by name, so a config short of one says
    # which, and in which file, rather than a bare KeyError from a launcher
    # with no console to raise into.
    path, raw = read_json_config(Path(config_path) if config_path else DEFAULT_CONFIG_PATH,
                                 default_dir=PROJECT_DIR)
    base = path.parent
    genau_raw = require_section(raw, "genau", path)

    def genau_value(key: str, cast: type):
        return require_typed(genau_raw, key, path, cast=cast, context="config.genau")

    return ProjectConfig(
        clips_dir=require_path(raw, "clips_dir", path, base=base),
        state_dir=require_path(raw, "state_dir", path, base=base),
        genau=GenauConfig(
            shuffle_on_load=genau_value("shuffle_on_load", bool),
            beats_per_loop=genau_value("beats_per_loop", float),
            clip_cache_size=genau_value("clip_cache_size", int),
            bpm_smoothing=genau_value("bpm_smoothing", float),
            sync_strength=genau_value("sync_strength", float),
            udp_host=genau_value("udp_host", str),
            udp_port=genau_value("udp_port", int),
            notify_host=genau_value("notify_host", str),
            notify_port=genau_value("notify_port", int),
            resize_debounce_ms=genau_value("resize_debounce_ms", int),
            tcode_udp_host=str(genau_raw.get("tcode_udp_host", "127.0.0.1")),
            tcode_udp_port=int(genau_raw.get("tcode_udp_port", 50557)),
        ),
    )
