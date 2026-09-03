"""The first clip's decode, running beside the window it does not need.

It was a closure in run_listener writing into a one-key dict, started and joined
seventy lines apart, and nothing in the suite reached any of it: the failure
path in particular -- a clip that will not decode -- had never been run.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from genau.first_clip import FirstClipPreload

CLIP = Path("scene one.mp4")


def _logger() -> logging.Logger:
    return logging.getLogger("test.first_clip")


class TestADecodeThatWorks:
    def test_the_frames_are_there_once_it_is_waited_for(self):
        preload = FirstClipPreload(CLIP, lambda _path: ["a", "b"], _logger())
        preload.start()

        assert preload.wait() == ["a", "b"]

    def test_it_decodes_the_clip_it_was_given(self):
        asked: list[Path] = []
        preload = FirstClipPreload(CLIP, lambda path: asked.append(path) or [], _logger())
        preload.start()
        preload.wait()

        assert asked == [CLIP]

    def test_it_really_does_run_beside_the_caller(self):
        """The whole point: the caller goes on building a window while this
        runs, and only then waits."""
        started = threading.Event()
        let_go = threading.Event()

        def _slow(_path):
            started.set()
            let_go.wait(timeout=2.0)
            return ["frame"]

        preload = FirstClipPreload(CLIP, _slow, _logger())
        preload.start()

        assert started.wait(timeout=2.0), "the decode did not start on its own"
        assert preload.frames is None      # the caller is still free
        let_go.set()
        assert preload.wait() == ["frame"]


class TestADecodeThatDoesNot:
    def test_a_failure_is_not_a_failed_launch(self, caplog):
        """The clip is still shown; it is simply decoded again on the main path,
        a beat later, the way any other clip is."""
        def _broken(_path):
            raise OSError("the file is not a video")

        preload = FirstClipPreload(CLIP, _broken, _logger())
        preload.start()

        with caplog.at_level("WARNING", logger="test.first_clip"):
            assert preload.wait() is None

    def test_the_reason_reaches_the_log_with_its_traceback(self, caplog):
        def _broken(_path):
            raise OSError("the file is not a video")

        preload = FirstClipPreload(CLIP, _broken, _logger())
        with caplog.at_level("WARNING", logger="test.first_clip"):
            preload.start()
            preload.wait()

        assert "scene one.mp4" in caplog.text
        assert caplog.records[-1].exc_info is not None


class TestADecodeThatTakesTooLong:
    def test_the_wait_gives_up_rather_than_holding_the_window_closed(self):
        """A decode that has gone wrong must not keep the window from opening."""
        never = threading.Event()
        preload = FirstClipPreload(CLIP, lambda _path: never.wait(), _logger())
        preload.start()

        assert preload.wait(timeout=0.05) is None

    def test_the_default_wait_is_the_one_the_launch_uses(self):
        assert FirstClipPreload.JOIN_TIMEOUT_S == 10.0
