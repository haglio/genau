from __future__ import annotations

import random
import subprocess
from pathlib import Path

import numpy as np
from app_support.subprocess_utils import hidden_subprocess_kwargs

SUPPORTED_VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}


def _modified_at(path: Path) -> float:
    """*path*'s modification time; one we cannot stat sorts oldest."""
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def scan_clips(
    folder: Path, *, shuffle_on_load: bool = True, recent: bool = False,
    shuffle=random.shuffle,
) -> list[Path]:
    """Every clip in *folder*, in the browse order asked for.

    *recent* is Latest — newest-first, so the clips that have just arrived head
    the sequence — and it outranks *shuffle_on_load*: an order named outright is
    not then randomized away.  Without it the folder's own order stands,
    shuffled when the config says to.

    *shuffle* is a dependency rather than a module global so the shuffled order
    can be asked about at all: the reorder path is otherwise only testable by
    running it until a different order comes out.
    """
    files = [path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in SUPPORTED_VIDEO_EXTS]
    if not files:
        raise RuntimeError(f"No video clips found in: {folder}")
    if recent:
        return sorted(files, key=_modified_at, reverse=True)
    if shuffle_on_load:
        shuffle(files)
    return files


def ffprobe_size(path: Path) -> tuple[int, int]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "csv=p=0:s=x",
        str(path),
    ]
    out = subprocess.check_output(cmd, text=True, **hidden_subprocess_kwargs()).strip()
    width, height = out.split("x", 1)
    return int(width), int(height)


def decode_video_to_numpy_frames(path: Path) -> list[np.ndarray]:
    width, height = ffprobe_size(path)
    frame_size = width * height * 3

    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(path),
        "-map",
        "0:v:0",
        "-an",
        "-sn",
        "-vsync",
        "0",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "pipe:1",
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **hidden_subprocess_kwargs())
    frames: list[np.ndarray] = []

    try:
        while True:
            buf = proc.stdout.read(frame_size) if proc.stdout else b""
            if not buf:
                break
            if len(buf) != frame_size:
                break
            frames.append(
                np.frombuffer(buf, dtype=np.uint8).reshape((height, width, 3)).copy()
            )
    finally:
        if proc.stdout:
            proc.stdout.close()
        stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
        rc = proc.wait()
        if rc != 0:
            raise RuntimeError(stderr.strip() or f"ffmpeg failed for {path}")

    if not frames:
        raise RuntimeError(f"No frames decoded from: {path}")

    return frames


def cache_dir_for_clips_folder(folder: Path) -> Path:
    return folder.parent / "frames"


def load_clip_frames(video_path: Path, cache_dir: Path) -> list[np.ndarray]:
    from .frame_cache import read_rhcache_all_frames

    cache_path = cache_dir / (video_path.stem + ".rhcache")
    if cache_path.exists():
        return read_rhcache_all_frames(cache_path)

    return decode_video_to_numpy_frames(video_path)
