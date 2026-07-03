from __future__ import annotations

import numpy as np

from nau.overlay import RecordingStrip, indicator_for


class TestIndicatorFor:
    def test_playing_shows_play(self):
        assert indicator_for("normal", paused=False) == "play"

    def test_paused_shows_pause(self):
        assert indicator_for("normal", paused=True) == "pause"

    def test_recording_shows_record_even_when_paused(self):
        assert indicator_for("recording", paused=False) == "record"
        assert indicator_for("recording", paused=True) == "record"

    def test_looping_shows_loop(self):
        assert indicator_for("looping", paused=False) == "loop"

    def test_paused_trumps_looping(self):
        assert indicator_for("looping", paused=True) == "pause"


def _frame(w=160, h=90):
    return np.full((h, w, 3), 128, dtype=np.uint8)


class TestRecordingStrip:
    def test_inactive_until_recording_state_seen(self):
        strip = RecordingStrip(tile_height=45, max_width=800)

        strip.update("normal", 1000.0, _frame())

        assert strip.thumbnails == []
        assert strip.bar_width_px(1000.0) == 0

    def test_captures_first_thumbnail_immediately_on_record(self):
        strip = RecordingStrip(tile_height=45, max_width=800)

        strip.update("recording", 2500.0, _frame())

        assert len(strip.thumbnails) == 1
        thumb = strip.thumbnails[0]
        assert thumb.shape[0] == 45
        assert thumb.shape[1] == 80  # 16:9 frame at height 45

    def test_captures_one_thumbnail_per_second(self):
        strip = RecordingStrip(tile_height=45, max_width=800)

        strip.update("recording", 2500.0, _frame())
        strip.update("recording", 3100.0, _frame())  # 0.6s in — too soon
        assert len(strip.thumbnails) == 1

        strip.update("recording", 3500.0, _frame())  # 1.0s in
        assert len(strip.thumbnails) == 2

        strip.update("recording", 5900.0, _frame())  # 3.4s in — catches up one tile
        assert len(strip.thumbnails) == 3

    def test_bar_grows_with_recorded_time(self):
        strip = RecordingStrip(tile_height=45, max_width=800)
        strip.update("recording", 2500.0, _frame())

        assert strip.bar_width_px(2500.0) == 0
        assert strip.bar_width_px(3000.0) == 40  # half a second = half a tile
        assert strip.bar_width_px(4500.0) == 160

    def test_bar_and_thumbnails_capped_at_max_width(self):
        strip = RecordingStrip(tile_height=45, max_width=200)  # room for 2.5 tiles

        for i in range(6):
            strip.update("recording", 1000.0 * i, _frame())

        assert len(strip.thumbnails) == 2  # third tile would overflow
        assert strip.bar_width_px(60_000.0) == 200

    def test_leaving_recording_state_clears_strip(self):
        strip = RecordingStrip(tile_height=45, max_width=800)
        strip.update("recording", 2500.0, _frame())

        strip.update("looping", 3500.0, _frame())

        assert strip.thumbnails == []
        assert strip.bar_width_px(9999.0) == 0

    def test_none_frame_does_not_consume_capture_slot(self):
        strip = RecordingStrip(tile_height=45, max_width=800)

        strip.update("recording", 2500.0, None)
        assert strip.thumbnails == []

        strip.update("recording", 2600.0, _frame())
        assert len(strip.thumbnails) == 1
