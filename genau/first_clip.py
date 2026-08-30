"""The first clip's decode, running beside the window it does not need.

Decoding a clip is the longest thing at startup and the window does not depend
on it, so the two overlap: the decode starts before the window is built and is
waited for only once everything else is wired.  Both halves are load-bearing --
started after the window, the window comes up and then freezes for the decode,
which is the whole of what the thread is for; waited for next to the start, the
thread buys nothing at all.

A failed decode is not a failed launch.  The clip is still shown; it is simply
decoded again on the main path, a beat later, the way any other clip is.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path


class FirstClipPreload:
    """One decode in flight, and the frames it produced."""

    # Long enough for a large clip on a cold cache, short enough that a decode
    # which has gone wrong does not hold the window closed indefinitely.
    JOIN_TIMEOUT_S = 10.0

    def __init__(self, path: Path, decode, logger: logging.Logger):
        self.path = path
        self.decode = decode
        self.logger = logger
        self.frames: list | None = None
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="genau-preload",
        )

    def _run(self) -> None:
        try:
            self.frames = self.decode(self.path)
        except Exception:
            self.logger.warning(
                "Failed to pre-load first clip %s", self.path, exc_info=True)

    def start(self) -> None:
        self._thread.start()

    def wait(self, timeout: float | None = None) -> list | None:
        """Give the decode what time is left, and say what it produced."""
        self._thread.join(
            timeout=self.JOIN_TIMEOUT_S if timeout is None else timeout)
        return self.frames
