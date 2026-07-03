"""Argument parsing and playlist resolution for Nau — no pygame imports.

Kept apart from the app shell so the orchestrator-facing configuration
surface is importable (and testable) without an SDL display.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .discovery import discover_videos
from .playlist import read_playlist

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "genau_config.json"


def load_config(config_path: Path) -> dict:
    if config_path.exists():
        return json.loads(config_path.read_text())
    return {}


def build_parser(config: dict) -> argparse.ArgumentParser:
    nau = config.get("nau", {})
    p = argparse.ArgumentParser(description="Nau — funscript video player")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--videos-dir", type=Path, default=nau.get("videos_dir"))
    p.add_argument("--scripts-dir", type=Path, default=nau.get("scripts_dir"))
    p.add_argument("--playlist", type=Path, default=None,
                   help="Video/funscript pair file (overrides directory discovery)")
    p.add_argument("--width", type=int, default=1200)
    p.add_argument("--height", type=int, default=900)
    p.add_argument("--x", type=int, default=None)
    p.add_argument("--y", type=int, default=None)
    p.add_argument("--tcode-host", default=nau.get("tcode_udp_host", "127.0.0.1"))
    p.add_argument("--tcode-port", type=int, default=nau.get("tcode_udp_port", 50557))
    p.add_argument("--command-file", type=Path, default=None,
                   help="Poll this file for orchestrator commands")
    p.add_argument("--paused-file", type=Path, default=None,
                   help="Flag file that owns the paused state when present")
    p.add_argument("--status-file", type=Path, default=None,
                   help="Publish playback status to this file")
    p.add_argument("--no-audio", action="store_true", default=False,
                   help="Never extract or play audio (silent)")
    return p


def audio_muted(args) -> bool:
    """Whether Nau should stay silent.

    Honors ``--no-audio`` and the ``FUN_TIME_MUTE_AUDIO=1`` contract the
    rest of the stack uses, so a Fun Time integration run never spends
    ffmpeg on audio it will not play.
    """
    import os

    return bool(args.no_audio) or os.environ.get("FUN_TIME_MUTE_AUDIO") == "1"


def resolve_playlist(args) -> list[tuple[Path, Path | None]]:
    if args.playlist is not None:
        return read_playlist(Path(args.playlist))
    if args.videos_dir is None or args.scripts_dir is None:
        return []
    return discover_videos(Path(args.videos_dir), Path(args.scripts_dir))
