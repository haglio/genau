from __future__ import annotations

import json
import zipfile
from pathlib import Path

import cv2
import numpy as np
import pytest

from genau_vr.clip import cache_dir_for_clips_folder, load_clip


class TestCacheDirForClipsFolder:
    def test_returns_sibling_frames_dir(self):
        clips = Path("C:/videos/robot_hand/clips")
        assert cache_dir_for_clips_folder(clips) == Path("C:/videos/robot_hand/frames")


class TestLoadClip:
    def test_loads_from_rhcache(self, tmp_path):
        clips_dir = tmp_path / "clips"
        clips_dir.mkdir()
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()

        # Create a tiny .rhcache with 2 frames
        frame = np.zeros((4, 6, 3), dtype=np.uint8)
        frame[1, 2] = [255, 0, 0]
        bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        ok, buf = cv2.imencode(".webp", bgr, [cv2.IMWRITE_WEBP_QUALITY, 95])
        assert ok

        cache_path = frames_dir / "test_clip.rhcache"
        meta = {"width": 6, "height": 4, "frame_count": 2, "source": "test"}
        with zipfile.ZipFile(cache_path, "w", compression=zipfile.ZIP_STORED) as zf:
            zf.writestr("meta.json", json.dumps(meta))
            zf.writestr("frames/000000.webp", buf.tobytes())
            zf.writestr("frames/000001.webp", buf.tobytes())

        # Create a dummy video file so the path exists
        video_path = clips_dir / "test_clip.mp4"
        video_path.write_bytes(b"dummy")

        frames = load_clip(video_path)
        assert len(frames) == 2
        assert frames[0].shape == (4, 6, 3)
