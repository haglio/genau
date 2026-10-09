"""The clip's row at the console's foot: its time on screen on the track, its loop on the dial."""
from __future__ import annotations

from types import SimpleNamespace

from player_core.clip_advance import ClipAdvanceState, set_elapsed
from player_core.playhead import video_playhead
from player_core.volume import VolumeHud

from genau.clip_row import ClipRow


def _following(turn=7 / 20, *, advance=None) -> ClipRow:
    row = ClipRow()
    row.follow(SimpleNamespace(loop_turn=turn), advance or ClipAdvanceState())
    return row


class TestTheTrack:
    def test_it_runs_the_time_the_clip_has_had_of_its_turn_on_screen(self):
        advance = ClipAdvanceState(locked=False, interval=10)
        set_elapsed(advance, 4.0)

        hud = _following(advance=advance).hud(VolumeHud())

        assert (hud.position_ms, hud.duration_ms) == (4_000, 10_000)
        assert hud.playhead == video_playhead(4_000, 10_000, 0)

    def test_it_carries_the_level_the_chip_is_showing(self):
        hud = _following().hud(VolumeHud(volume=40, muted=True))

        assert hud.volume == VolumeHud(volume=40, muted=True)

    def test_the_interval_is_what_a_press_along_it_is_measured_against(self):
        assert _following(advance=ClipAdvanceState(interval=7)).interval_ms == 7_000


class TestTheDial:
    def test_the_row_carries_the_turn_the_renderer_has_reached(self):
        assert _following(turn=7 / 20).hud(VolumeHud()).loop_turn == 7 / 20


class TestWithNoClipUp:
    def test_before_anything_is_followed_there_is_nothing_to_show(self):
        assert ClipRow().loop_turn() is None
        assert ClipRow().hud(VolumeHud()) is None

    def test_a_clip_still_decoding_has_no_frame_to_be_on(self):
        row = _following(turn=None)

        assert row.loop_turn() is None
        assert row.hud(VolumeHud()) is None
