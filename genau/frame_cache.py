from __future__ import annotations

import json
import zipfile
from pathlib import Path

import cv2
import numpy as np


def read_rhcache_meta(cache_path: Path) -> dict:
    with zipfile.ZipFile(cache_path, "r") as zf:
        return json.loads(zf.read("meta.json"))


def _decode_webp_rgb(buf: bytes) -> np.ndarray:
    arr = np.frombuffer(buf, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def read_rhcache_all_frames(cache_path: Path) -> list[np.ndarray]:
    meta = read_rhcache_meta(cache_path)
    frames: list[np.ndarray] = []
    with zipfile.ZipFile(cache_path, "r") as zf:
        for i in range(meta["frame_count"]):
            frames.append(_decode_webp_rgb(zf.read(f"frames/{i:06d}.webp")))
    return frames


