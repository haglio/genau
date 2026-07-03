from __future__ import annotations

import random
from pathlib import Path

from genau.video import SUPPORTED_VIDEO_EXTS


def discover_videos(
    videos_dir: Path,
    scripts_dir: Path,
) -> list[tuple[Path, Path | None]]:
    """Pair every video under *videos_dir* with its funscript, if any.

    Videos without a matching funscript are included with ``None`` — they
    play normally, but loop recording and OSR2 output stay inert.
    """
    pairs: list[tuple[Path, Path | None]] = []
    for video in videos_dir.rglob("*"):
        if not video.is_file() or video.suffix.lower() not in SUPPORTED_VIDEO_EXTS:
            continue
        relative = video.relative_to(videos_dir)
        funscript = scripts_dir / relative.with_suffix(".funscript")
        pairs.append((video, funscript if funscript.exists() else None))
    random.shuffle(pairs)
    return pairs
