from __future__ import annotations

import random
from pathlib import Path

SUPPORTED_VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}


def discover_videos(
    videos_dir: Path,
    scripts_dir: Path,
) -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []
    for video in videos_dir.rglob("*"):
        if not video.is_file() or video.suffix.lower() not in SUPPORTED_VIDEO_EXTS:
            continue
        relative = video.relative_to(videos_dir)
        funscript = scripts_dir / relative.with_suffix(".funscript")
        if funscript.exists():
            pairs.append((video, funscript))
    random.shuffle(pairs)
    return pairs
