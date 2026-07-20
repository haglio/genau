"""Nau's volume control: what it shows, and where a click on it lands."""
from __future__ import annotations

import numpy as np

from nau.volume import (
    CHIP_H,
    CHIP_W,
    SPEAKER_W,
    VolumeHud,
    VolumeHudPainter,
    chip_xy,
    hit_part,
    volume_at,
)


class TestPlacement:
    def test_the_chip_sits_at_the_right_edge_above_the_timeline(self):
        """Where a player's volume control has always been — beside the transport,
        not up in the corner where the mode furniture lives."""
        x, y = chip_xy(win_w=1200, win_h=900, timeline_h=40)

        assert x + CHIP_W <= 1200
        assert x > 1200 // 2, "right-hand side"
        assert y + CHIP_H <= 900 - 40, "clear of the timeline"

    def test_a_window_narrower_than_the_chip_still_places_it(self):
        """Clamped rather than pushed off the left edge, so it stays clickable."""
        x, _y = chip_xy(win_w=80, win_h=200, timeline_h=40)

        assert x >= 0


class TestHitTesting:
    def test_the_speaker_takes_the_left_end_and_the_track_the_rest(self):
        assert hit_part(2, CHIP_H // 2) == "mute"
        assert hit_part(CHIP_W - 4, CHIP_H // 2) == "track"

    def test_a_press_outside_the_chip_hits_nothing(self):
        assert hit_part(-1, CHIP_H // 2) == ""
        assert hit_part(CHIP_W + 1, CHIP_H // 2) == ""
        assert hit_part(2, CHIP_H + 5) == ""

    def test_the_track_reads_left_to_right_as_silent_to_full(self):
        assert volume_at(-999) == 0
        assert volume_at(999) == 100

    def test_the_track_is_linear_between_its_ends(self):
        """Equal steps along the track are equal steps in level, so the handle
        lands where it was put rather than somewhere near it."""
        step = (CHIP_W - SPEAKER_W) // 4
        low, mid, high = (volume_at(SPEAKER_W + n * step) for n in (0, 1, 2))

        assert low < mid < high
        assert abs((mid - low) - (high - mid)) <= 1


class TestPainter:
    def _chip(self, **kw) -> np.ndarray:
        return VolumeHudPainter().bgra(VolumeHud(**kw))

    def test_the_filled_part_of_the_track_grows_with_the_level(self):
        # Only the fill is near-white; the empty track and the chip's border are
        # both mid-grey, so a high threshold counts the fill and nothing else.
        def filled(volume: int) -> int:
            chip = self._chip(volume=volume)
            return int((chip[:, SPEAKER_W:, :3].sum(axis=2) > 600).sum())

        assert filled(20) < filled(60) < filled(100)

    def test_a_muted_control_still_shows_the_level_underneath_it(self):
        """The level survives a mute — it is what unmuting returns to — so the
        track keeps its fill and the speaker alone says silent."""
        loud = self._chip(volume=80, muted=False)
        silenced = self._chip(volume=80, muted=True)

        assert not np.array_equal(loud, silenced), "a mute has to look different"
        track = slice(CHIP_W // 3, CHIP_W)
        assert np.array_equal(loud[:, track], silenced[:, track]), "the level is unchanged"

    def test_an_unchanged_control_is_not_repainted(self):
        """Asked for every frame at 60fps; Pillow is nowhere near that cheap."""
        painter = VolumeHudPainter()

        assert painter.bgra(VolumeHud(volume=50)) is painter.bgra(VolumeHud(volume=50))

    def test_a_changed_level_is_repainted(self):
        painter = VolumeHudPainter()

        assert not np.array_equal(
            painter.bgra(VolumeHud(volume=50)), painter.bgra(VolumeHud(volume=51)))
