"""Configuration loader for Genau."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_DIR / "genau_config.json"


def _resolve_path(base: Path, raw: str) -> Path:
    p = Path(raw)
    return p if p.is_absolute() else (base / p).resolve()


@dataclass(frozen=True)
class VoiceConfig:
    model_path: str = "vosk-model-small-en-us-0.15"
    confidence_threshold: float = 0.7
    device_index: int | None = None
    sample_rate: int = 16000


@dataclass(frozen=True)
class GenauConfig:
    shuffle_on_load: bool
    beats_per_loop: float
    clip_cache_size: int
    render_batch: int
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
    project_dir: Path
    config_path: Path
    clips_dir: Path
    state_dir: Path
    genau: GenauConfig
    broker_cmd_file: Path
    voice: VoiceConfig | None = None

    @property
    def genau_cmd_file(self) -> Path:
        return self.state_dir / "genau_cmd.txt"

    @property
    def genau_paused_file(self) -> Path:
        return self.state_dir / "genau_paused.txt"

    @property
    def genau_drive_file(self) -> Path:
        """Where Genau says what it is driving the device with, for Nau to draw.

        In Hybrid the readout belongs to Nau's console — the controls that move
        these numbers are on it — so Genau publishes rather than paints.
        """
        return self.state_dir / "genau_drive.txt"

    @property
    def logs_dir(self) -> Path:
        return self.state_dir

    def log_file(self, name: str) -> Path:
        return self.logs_dir / f"{name}.log"


def load_config(config_path: str | Path | None = None) -> ProjectConfig:
    path = Path(config_path).expanduser() if config_path else DEFAULT_CONFIG_PATH
    if not path.is_absolute():
        path = (PROJECT_DIR / path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as fp:
        raw: dict[str, Any] = json.load(fp)

    base = path.parent

    genau_raw = raw.get("genau")
    if genau_raw is None:
        raise ValueError(f"Missing required config section: genau (in {path})")

    state_dir = _resolve_path(base, raw["state_dir"])
    broker_cmd_raw = raw.get("broker_cmd_file")
    broker_cmd_file = _resolve_path(base, broker_cmd_raw) if broker_cmd_raw else state_dir / "broker_cmd.txt"

    return ProjectConfig(
        project_dir=base,
        config_path=path,
        clips_dir=_resolve_path(base, raw["clips_dir"]),
        state_dir=state_dir,
        genau=GenauConfig(
            shuffle_on_load=bool(genau_raw["shuffle_on_load"]),
            beats_per_loop=float(genau_raw["beats_per_loop"]),
            clip_cache_size=int(genau_raw["clip_cache_size"]),
            render_batch=int(genau_raw["render_batch"]),
            bpm_smoothing=float(genau_raw["bpm_smoothing"]),
            sync_strength=float(genau_raw["sync_strength"]),
            udp_host=str(genau_raw["udp_host"]),
            udp_port=int(genau_raw["udp_port"]),
            notify_host=str(genau_raw["notify_host"]),
            notify_port=int(genau_raw["notify_port"]),
            resize_debounce_ms=int(genau_raw["resize_debounce_ms"]),
            tcode_udp_host=str(genau_raw.get("tcode_udp_host", "127.0.0.1")),
            tcode_udp_port=int(genau_raw.get("tcode_udp_port", 50557)),
        ),
        broker_cmd_file=broker_cmd_file,
        voice=_parse_voice_config(raw.get("voice_control")),
    )


def _parse_voice_config(raw: dict[str, Any] | None) -> VoiceConfig | None:
    if raw is None:
        return None
    return VoiceConfig(
        model_path=str(raw.get("model_path", VoiceConfig.model_path)),
        confidence_threshold=float(raw.get("confidence_threshold", VoiceConfig.confidence_threshold)),
        device_index=raw.get("device_index"),
        sample_rate=int(raw.get("sample_rate", VoiceConfig.sample_rate)),
    )
