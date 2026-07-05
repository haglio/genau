"""Argument parsing and playlist resolution for Nau — no pygame imports.

Kept apart from the app shell so the orchestrator-facing configuration
surface is importable (and testable) without an SDL display.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from .duration_cache import DurationCache
from .library_source import DEFAULT_MODE, LibrarySource, build_library_source
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
    p.add_argument("--clips-dir", type=Path, default=nau.get("clips_dir") or config.get("clips_dir"),
                   help="Saved short clips, always included in shorts mode")
    p.add_argument("--state-dir", type=Path, default=config.get("state_dir"),
                   help="Where the duration cache is stored")
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


def _duration_cache_path(args) -> Path:
    base = Path(args.state_dir) if args.state_dir else Path(args.config).resolve().parent
    return base / "nau_durations.json"


def library_source(
    args,
    *,
    rng: random.Random | None = None,
    durations: dict[Path, float] | None = None,
) -> LibrarySource | None:
    """Build the :class:`LibrarySource`, or None when the library dirs are absent.

    Built whenever ``--videos-dir``/``--scripts-dir`` are known — including under
    Fun Time, which passes its own ``--playlist`` for the *initial* selection but
    still needs this source for version cycling and the shorts/full-length
    toggle.  *durations* is a test seam; production probes via the cache.
    """
    if args.videos_dir is None or args.scripts_dir is None:
        return None
    return build_library_source(
        Path(args.videos_dir),
        Path(args.scripts_dir),
        Path(args.clips_dir) if args.clips_dir else None,
        rng=rng or random.Random(),
        duration_cache=None if durations is not None else DurationCache(_duration_cache_path(args)),
        durations=durations,
    )


def resolve_playlist(
    args,
    *,
    durations: dict[Path, float] | None = None,
    rng: random.Random | None = None,
) -> list[tuple[Path, Path | None]]:
    """Initial playlist: explicit file verbatim, else deduped full-length discovery.

    *durations* and *rng* are injectable seams for tests; production leaves them
    None to probe (cached) and shuffle nondeterministically.
    """
    if args.playlist is not None:
        return read_playlist(Path(args.playlist))
    source = library_source(args, rng=rng, durations=durations)
    if source is None:
        return []
    return source.playlist_for(DEFAULT_MODE)
