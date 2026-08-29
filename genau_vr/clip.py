"""Clip loading for GenauVR.

Copied from Genau's video.py and frame_cache.py — simplified to load a
single clip synchronously with no caching or prefetch.
"""
from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import cv2
import numpy as np

SUPPORTED_VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}


def _subprocess_kwargs() -> dict:
    if sys.platform != "win32":
        return {}
    return {
        "startupinfo": _hidden_startupinfo(),
        "creationflags": subprocess.CREATE_NO_WINDOW,
    }


def _hidden_startupinfo() -> subprocess.STARTUPINFO:
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0
    return si


def cache_dir_for_clips_folder(folder: Path) -> Path:
    return folder.parent / "frames"


def _decode_webp_rgb(buf: bytes) -> np.ndarray:
    arr = np.frombuffer(buf, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def _read_rhcache_all_frames(cache_path: Path) -> list[np.ndarray]:
    with zipfile.ZipFile(cache_path, "r") as zf:
        meta = json.loads(zf.read("meta.json"))
        frames: list[np.ndarray] = []
        for i in range(meta["frame_count"]):
            frames.append(_decode_webp_rgb(zf.read(f"frames/{i:06d}.webp")))
    return frames


def _ffprobe_size(path: Path) -> tuple[int, int]:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0:s=x",
        str(path),
    ]
    out = subprocess.check_output(cmd, text=True, **_subprocess_kwargs()).strip()
    width, height = out.split("x", 1)
    return int(width), int(height)


def _decode_video_to_numpy_frames(path: Path) -> list[np.ndarray]:
    width, height = _ffprobe_size(path)
    frame_size = width * height * 3

    cmd = [
        "ffmpeg", "-v", "error",
        "-i", str(path),
        "-map", "0:v:0", "-an", "-sn",
        "-vsync", "0",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "pipe:1",
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **_subprocess_kwargs())
    frames: list[np.ndarray] = []

    try:
        while True:
            buf = proc.stdout.read(frame_size) if proc.stdout else b""
            if not buf or len(buf) != frame_size:
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


def load_clip(video_path: Path) -> list[np.ndarray]:
    """Load all frames for a single clip.

    Tries .rhcache first (fast), falls back to ffmpeg decode.
    """
    cache_dir = cache_dir_for_clips_folder(video_path.parent)
    cache_path = cache_dir / (video_path.stem + ".rhcache")
    if cache_path.exists():
        return _read_rhcache_all_frames(cache_path)
    return _decode_video_to_numpy_frames(video_path)


def scan_clips(folder: Path) -> list[Path]:
    """Find all video files in a folder."""
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_VIDEO_EXTS]
    if not files:
        raise RuntimeError(f"No video clips found in: {folder}")
    return sorted(files)
