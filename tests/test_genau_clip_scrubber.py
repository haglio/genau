"""The clip's playhead, and the bar Genau's window draws from it."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
from player_core.timeline import TIMELINE_HEIGHT

from genau.clip_scrubber import ClipScrubber


def _renderer(index, frames):
    return SimpleNamespace(
        current_frame_index=index,
        current_clip_entry=lambda: None if frames is None else {"frames": frames},
    )


def _following(index=5, count=20) -> ClipScrubber:
    scrubber = ClipScrubber()
    scrubber.follow(_renderer(index, [object()] * count))
    return scrubber


class TestThePlayhead:
    def test_before_a_renderer_is_following_there_is_nothing_to_show(self):
        assert ClipScrubber().playhead() == (0, 0)
        assert ClipScrubber().bgra(640) is None

    def test_it_counts_up_while_the_frame_that_is_up_counts_down(self):
        """player_core shows a clip from its last frame back, so the cursor drawn
        straight off that index walked backwards along the bar."""
        assert _following(index=19, count=20).playhead() == (0, 20)
        assert _following(index=12, count=20).playhead() == (7, 20)
        assert _following(index=0, count=20).playhead() == (19, 20)

    def test_a_clip_still_decoding_has_no_frame_to_be_on(self):
        scrubber = ClipScrubber()
        scrubber.follow(_renderer(None, None))

        assert scrubber.playhead() == (0, 0)
        assert scrubber.bgra(640) is None


class TestTheBar:
    def test_it_spans_the_window_at_the_height_nau_draws_one(self):
        assert _following().bgra(640).shape == (TIMELINE_HEIGHT, 640, 4)

    def test_the_cursor_moves_as_the_hand_moves_the_loop(self):
        assert not np.array_equal(
            _following(index=1).bgra(640), _following(index=18).bgra(640))

    def test_a_window_with_no_width_yet_draws_nothing(self):
        assert _following().bgra(0) is None
