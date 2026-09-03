"""The shared genau_config.json, read into something with names.

GenauVR read the same file Genau does into a bare dict and passed it to five
functions, each digging out its own keys with ``.get()`` and its own inline
default -- so a mistyped key was a silent default rather than an error, and two
settings that exist in the config were hardcoded at the call site instead of
read.  This is the same discipline genau/config.py already applies to the same
file, for the half of it GenauVR uses.

Absent keys still take their defaults: GenauVR is launched from a shortcut with
no console, and a headset that comes up on a default is better than one that
shows a dialog and quits.  What *is* refused is a clips folder that names
nothing, because there is nothing to show.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "genau_config.json"

# Where the T-Code goes when the config does not say.  The device's own
# listener, on the port Genau uses for the same thing.
DEFAULT_TCODE_HOST = "127.0.0.1"
DEFAULT_TCODE_PORT = 50557

DEFAULT_STATE_DIR = "state"

# The voice model and how sure it has to be, when the config does not say.
DEFAULT_VOICE_MODEL = "vosk-model-small-en-us-0.15"
DEFAULT_VOICE_CONFIDENCE = 0.7
DEFAULT_VOICE_SAMPLE_RATE = 16000


@dataclass(frozen=True)
class VoiceConfig:
    model_path: str = DEFAULT_VOICE_MODEL
    confidence_threshold: float = DEFAULT_VOICE_CONFIDENCE
    device_index: int | None = None
    sample_rate: int = DEFAULT_VOICE_SAMPLE_RATE


@dataclass(frozen=True)
class VrConfig:
    """What GenauVR reads out of the shared config."""

    state_dir: Path
    tcode_host: str = DEFAULT_TCODE_HOST
    tcode_port: int = DEFAULT_TCODE_PORT
    # The VR180 clips, and the flat ones to fall back on when there are none.
    vr_clips_dir: Path | None = None
    clips_dir: Path | None = None
    voice: VoiceConfig = VoiceConfig()

    @property
    def tcode_endpoint(self) -> tuple[str, int]:
        return self.tcode_host, self.tcode_port


def _resolve(raw, against: Path) -> Path | None:
    """A path from the config, made absolute against the config's own folder.

    A relative path in a config is relative to the config, not to whatever
    directory the shortcut happened to start us in.
    """
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else against / path


def load_config(config_path: Path | None = None) -> VrConfig:
    path = config_path or DEFAULT_CONFIG
    raw: dict = {}
    if path.exists():
        try:
            with path.open(encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            logger.warning("Could not read %s; using defaults", path, exc_info=True)
    else:
        logger.warning("No config at %s; using defaults", path)

    beside = path.parent
    genau = raw.get("genau", {})
    voice = raw.get("voice_control", {})
    state_dir = _resolve(raw.get("state_dir", DEFAULT_STATE_DIR), beside)
    state_dir.mkdir(parents=True, exist_ok=True)
    return VrConfig(
        state_dir=state_dir,
        tcode_host=genau.get("tcode_udp_host", DEFAULT_TCODE_HOST),
        tcode_port=genau.get("tcode_udp_port", DEFAULT_TCODE_PORT),
        vr_clips_dir=_resolve(raw.get("vr_clips_dir"), beside),
        clips_dir=_resolve(raw.get("clips_dir"), beside),
        voice=VoiceConfig(
            model_path=voice.get("model_path", DEFAULT_VOICE_MODEL),
            confidence_threshold=voice.get(
                "confidence_threshold", DEFAULT_VOICE_CONFIDENCE),
            device_index=voice.get("device_index"),
            sample_rate=voice.get("sample_rate", DEFAULT_VOICE_SAMPLE_RATE),
        ),
    )


def clips_to_play(named: str | None, config: VrConfig) -> list[Path]:
    """The clips this run shows: the one named on the command line, or a folder.

    The VR180 folder first, the flat one after it -- and a vr_clips_dir that
    does not exist is *said* rather than silently skipped, because it is the
    setting a person most often gets wrong and the fallback hides it.
    """
    from .clip import scan_clips

    if named:
        clip = Path(named)
        if not clip.exists():
            raise FileNotFoundError(f"Clip not found: {clip}")
        return [clip]

    if config.vr_clips_dir is not None:
        if config.vr_clips_dir.exists():
            return scan_clips(config.vr_clips_dir)
        logger.warning("vr_clips_dir does not exist: %s", config.vr_clips_dir)

    if config.clips_dir is not None:
        return scan_clips(config.clips_dir)

    raise RuntimeError("No clip specified and no clips_dir in config")
