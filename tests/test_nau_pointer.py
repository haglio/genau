"""Where a press on Nau's window lands once the console has had its turn.

Three zones, all measured from the bottom of the window: the volume chip at the
right-hand end of the timeline row, the rest of that row, and the video above
it.  800x600 with no heatmap built puts the row's top edge at y=576, and the
inset track between x=40 and x=668.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from player_core.funscript import Funscript
from nau.dashboard import Dashboard
from nau.overlay import HeatmapStrip
from nau.pointer import Pointer
from nau.volume_control import VolumeControl

DURATION_MS = 100_000.0
ON_THE_VIDEO = (400, 300)
TRACK_START = (40, 590)
TRACK_MIDDLE = (354, 590)
PAST_THE_TRACKS_END = (790, 590)
ON_THE_VOLUME_CHIP = (744, 590)


class SpySession:
    """The player, as a press reaches it: where it was sent, and how often it
    was told to stop and start."""

    def __init__(self, duration_ms: float = DURATION_MS) -> None:
        self.duration_ms = duration_ms
        self.seeks: list[float] = []
        self.pause_toggles = 0

    def seek_to(self, position_ms: float) -> None:
        self.seeks.append(position_ms)

    def toggle_pause(self) -> None:
        self.pause_toggles += 1


def _funscript() -> Funscript:
    return Funscript(actions=[(0, 0), (1000, 100), (2000, 0)])


@pytest.fixture()
def bits(tmp_path: Path):
    """A pointer over a spy session, its strip, and its volume chip."""
    session = SpySession()
    heatmap = HeatmapStrip()
    volume = VolumeControl(Dashboard(tmp_path / "dashboard_cmd.txt"))
    return Pointer(session, heatmap, volume), session, heatmap, volume


class TestPressingTheVideo:
    def test_it_stops_and_starts_the_video(self, bits):
        pointer, session, _heatmap, _volume = bits

        pointer.press(*ON_THE_VIDEO, win_w=800, win_h=600)

        assert session.pause_toggles == 1
        assert session.seeks == []

    def test_a_press_just_above_the_timeline_row_is_still_the_video(self, bits):
        """The row is 24px tall with no strip built, so 575 is the last row of
        video and 576 the first of the timeline."""
        pointer, session, _heatmap, _volume = bits

        pointer.press(400, 575, win_w=800, win_h=600)

        assert session.pause_toggles == 1


class TestPressingTheTimeline:
    def test_it_seeks_and_does_not_touch_the_pause(self, bits):
        pointer, session, _heatmap, _volume = bits

        pointer.press(*TRACK_MIDDLE, win_w=800, win_h=600)

        assert session.seeks == [pytest.approx(DURATION_MS / 2)]
        assert session.pause_toggles == 0

    def test_the_start_of_the_track_is_the_start_of_the_video(self, bits):
        pointer, session, _heatmap, _volume = bits

        pointer.press(*TRACK_START, win_w=800, win_h=600)

        assert session.seeks == [pytest.approx(0.0)]

    def test_the_track_is_inset_so_the_left_edge_is_still_the_start(self, bits):
        """The track starts a margin in from the window edge; a press in that
        margin saturates rather than seeking to a negative time."""
        pointer, session, _heatmap, _volume = bits

        pointer.press(2, 590, win_w=800, win_h=600)

        assert session.seeks == [pytest.approx(0.0)]

    def test_past_the_end_of_the_track_is_the_end_of_the_video(self, bits):
        """The track stops clear of the volume chip, so the pixels between the
        two are past the end rather than off the map."""
        pointer, session, _heatmap, _volume = bits

        pointer.press(*PAST_THE_TRACKS_END, win_w=800, win_h=600)

        assert session.seeks == [pytest.approx(DURATION_MS)]

    def test_a_taller_strip_makes_the_row_reach_further_up_the_window(self, bits):
        """A loop being recorded grows the strip to 48px, so a press at 560 --
        video a moment ago -- is a seek now."""
        pointer, session, heatmap, _volume = bits
        heatmap.update("v0.mp4", _funscript(), DURATION_MS, width=628,
                       loop_state="recording", record_in_ms=1000.0, position_ms=1200.0)

        pointer.press(354, 560, win_w=800, win_h=600)

        assert session.pause_toggles == 0
        assert len(session.seeks) == 1

    def test_it_seeks_inside_the_window_the_strip_is_showing(self, bits):
        """While recording, the strip is zoomed into the section around the in
        point, and the track under it maps that window rather than the whole
        video -- otherwise the picture and the press disagree."""
        pointer, session, heatmap, _volume = bits
        heatmap.update("v0.mp4", _funscript(), DURATION_MS, width=628,
                       loop_state="recording", record_in_ms=1000.0, position_ms=1200.0)
        start_ms, end_ms = heatmap.window

        pointer.press(*TRACK_MIDDLE, win_w=800, win_h=600)

        assert end_ms - start_ms < DURATION_MS, "the strip is not zoomed; case proves nothing"
        assert start_ms <= session.seeks[0] <= end_ms
        assert session.seeks[0] != pytest.approx(DURATION_MS / 2)

    def test_before_any_strip_is_built_the_video_own_length_is_the_map(self, bits):
        """The strip reports an empty window until its first build, and a press
        in that first frame still has to land somewhere sensible."""
        pointer, session, heatmap, _volume = bits

        assert heatmap.window == (0.0, 0.0)
        pointer.press(*TRACK_MIDDLE, win_w=800, win_h=600)

        assert session.seeks == [pytest.approx(DURATION_MS / 2)]


class TestPressingTheVolumeChip:
    def test_the_chip_takes_the_press_before_the_video_behind_it(self, bits):
        """It floats over the video, so a press on it is never also a press on
        what is behind it."""
        pointer, session, _heatmap, volume = bits

        pointer.press(*ON_THE_VOLUME_CHIP, win_w=800, win_h=600)

        assert volume.hud.volume == 50
        assert (session.seeks, session.pause_toggles) == ([], 0)


class TestDragging:
    def test_a_drag_reaches_the_volume_slider(self, bits):
        pointer, _session, _heatmap, volume = bits

        pointer.drag(*ON_THE_VOLUME_CHIP, win_w=800, win_h=600)

        assert volume.hud.volume == 50

    def test_a_drag_over_the_video_moves_nothing(self, bits):
        pointer, session, _heatmap, volume = bits

        pointer.drag(*ON_THE_VIDEO, win_w=800, win_h=600)

        assert volume.hud.volume == 100
        assert (session.seeks, session.pause_toggles) == ([], 0)
