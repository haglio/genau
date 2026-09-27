"""The clip's playhead, and the row the console draws from it."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from player_core.playhead import clip_playhead
from player_core.timeline import bar_track_x
from player_core.volume import VolumeHud

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
        assert ClipScrubber().row(VolumeHud()) is None

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
        assert scrubber.row(VolumeHud()) is None


class TestTheRow:
    def test_it_maps_the_frame_reached_against_how_many_there_are(self):
        """A clip is a loop of frames with no running time, so the track counts
        frames where a video's counts milliseconds."""
        row = _following(index=12, count=20).row(VolumeHud(volume=40))

        assert (row.position_ms, row.duration_ms) == (7, 20)

    def test_it_carries_the_level_the_chip_is_showing(self):
        row = _following().row(VolumeHud(volume=40, muted=True))

        assert row.volume == VolumeHud(volume=40, muted=True)

    def test_it_carries_the_frame_count_as_its_readout(self):
        row = _following(index=12, count=20).row(VolumeHud())

        assert row.playhead == clip_playhead(7, 20)


class TestWhereAPressAlongTheTrackLands:
    def test_the_start_of_the_track_is_the_start_of_the_loop(self):
        assert ClipScrubber.fraction_at(bar_track_x(400)[0], width=400) == 0.0

    def test_past_the_end_of_the_track_is_the_end_of_the_loop(self):
        assert ClipScrubber.fraction_at(400, width=400) == 1.0

    def test_halfway_along_it_is_halfway_through(self):
        x0, x1 = bar_track_x(400)

        assert ClipScrubber.fraction_at((x0 + x1) // 2, width=400) == pytest.approx(
            0.5, abs=1 / (x1 - x0))
