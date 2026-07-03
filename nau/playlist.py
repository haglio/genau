"""Nau playlist file: one video per line, optional TAB-separated funscript.

Fun Time owns video discovery and F-mode filtering; it writes this file and
tells Nau to RELOAD_PLAYLIST. Blank lines and #-comments are ignored.
"""
from __future__ import annotations

from pathlib import Path


def read_playlist(path: Path) -> list[tuple[Path, Path | None]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    pairs: list[tuple[Path, Path | None]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        video_part, _, funscript_part = line.partition("\t")
        video_part = video_part.strip()
        funscript_part = funscript_part.strip()
        if not video_part:
            continue
        pairs.append((Path(video_part), Path(funscript_part) if funscript_part else None))
    return pairs
