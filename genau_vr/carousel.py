"""The clips this session can show, and which frame of the one on screen.

The loop used to hold four of these as locals and rebind them through a
``nonlocal`` closure -- the clip list's position, the decoded frames, how many
there are, and which one is up -- so nothing could be tested without running the
loop, and the loop could not be split without carrying all four along.

Stepping and choosing a frame belong together because stepping invalidates the
choice: a new clip has its own frame count and no frame on screen yet, and the
phase starts again from the top.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from .clip import load_clip
from .playback import display_index_for_phase

logger = logging.getLogger(__name__)


class ClipCarousel:
    def __init__(
        self,
        clip_list: list[Path],
        frames: list[np.ndarray],
        *,
        audio=None,
        decode=load_clip,
    ):
        self.clip_list = clip_list
        self.frames = frames
        self.audio = audio
        self.decode = decode
        self.index = 0
        # No frame is up yet, which is not the same as frame zero being up.
        self.showing = -1

    @property
    def current_path(self) -> Path:
        return self.clip_list[self.index]

    def step(self, delta: int) -> bool:
        """Move to the next clip along, and say whether anything changed.

        A single-clip session steps nowhere: reloading the one clip would stop
        the picture and restart the sound for no move.
        """
        if len(self.clip_list) <= 1:
            return False
        self.index = (self.index + delta) % len(self.clip_list)
        new_path = self.current_path
        logger.info("Switching to clip: %s", new_path.name)
        self.frames = self.decode(new_path)
        self.showing = -1
        if self.audio is not None:
            self.audio.load_for_clip(new_path)
        return True

    def frame_for_phase(self, phase: float, *, auto_active: bool) -> np.ndarray | None:
        """The frame to upload, or None when it is the one already up.

        The comparison is the point: uploading a texture is the most expensive
        thing in the frame, and a paused clip would otherwise pay it every turn.
        """
        chosen = display_index_for_phase(
            phase=phase,
            frame_count=len(self.frames),
            auto_active=auto_active,
            current_frame_index=self.showing if self.showing >= 0 else None,
        )
        if chosen == self.showing:
            return None
        self.showing = chosen
        return self.frames[chosen]
