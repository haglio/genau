"""Builds the .rhcache files the reader tests read.

Genau only ever reads this format -- Evolver and Origenerator write the
real ones into the clips folder -- so the writer is fixture code and lives
here, next to the tests that need one.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import cv2
import numpy as np


def write_rhcache(
    frames: list[np.ndarray],
    output_path: Path,
    *,
    source_name: str = "",
    quality: int = 95,
    lossless: bool = False,
) -> None:
    if not frames:
        raise ValueError("frames list is empty")

    height, width = frames[0].shape[:2]
    meta = {
        "width": width,
        "height": height,
        "frame_count": len(frames),
        "source": source_name,
    }

    encode_quality = 101 if lossless else quality

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("meta.json", json.dumps(meta))
        for i, frame in enumerate(frames):
            bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            ok, buf = cv2.imencode(
                ".webp", bgr, [cv2.IMWRITE_WEBP_QUALITY, encode_quality]
            )
            if not ok:
                raise RuntimeError(f"WebP encode failed for frame {i}")
            zf.writestr(f"frames/{i:06d}.webp", buf.tobytes())
