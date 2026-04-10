from __future__ import annotations

from nau.playback import PlaybackClock


class TestPlaybackClock:
    def test_initial_position_is_zero(self):
        clock = PlaybackClock(now_source=lambda: 0.0)

        assert clock.position_ms == 0.0

    def test_advances_with_wall_clock(self):
        t = [0.0]
        clock = PlaybackClock(now_source=lambda: t[0])
        clock.start()

        t[0] = 0.5
        assert clock.position_ms == 500.0

    def test_pause_freezes_position(self):
        t = [0.0]
        clock = PlaybackClock(now_source=lambda: t[0])
        clock.start()
        t[0] = 1.0
        clock.pause()

        t[0] = 5.0

        assert clock.position_ms == 1000.0

    def test_resume_continues_from_paused_position(self):
        t = [0.0]
        clock = PlaybackClock(now_source=lambda: t[0])
        clock.start()
        t[0] = 1.0
        clock.pause()
        t[0] = 5.0
        clock.resume()

        t[0] = 6.0

        assert clock.position_ms == 2000.0

    def test_seek_sets_position(self):
        t = [0.0]
        clock = PlaybackClock(now_source=lambda: t[0])
        clock.start()
        t[0] = 1.0

        clock.seek(5000.0)

        assert clock.position_ms == 5000.0

    def test_seek_while_paused(self):
        t = [0.0]
        clock = PlaybackClock(now_source=lambda: t[0])
        clock.start()
        t[0] = 1.0
        clock.pause()

        clock.seek(3000.0)

        assert clock.position_ms == 3000.0

    def test_is_playing_property(self):
        clock = PlaybackClock(now_source=lambda: 0.0)

        assert not clock.is_playing
        clock.start()
        assert clock.is_playing
        clock.pause()
        assert not clock.is_playing
        clock.resume()
        assert clock.is_playing
