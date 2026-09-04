from __future__ import annotations

from player_core.funscript import Funscript

from nau.heatmap import _speed_to_color, build_heatmap

_NEAR_BLACK = (10, 14, 30)
_BLUE = (30, 70, 230)


class TestSpeedToColor:
    def test_gradient_anchors(self):
        assert _speed_to_color(0) == (10, 14, 30)  # idle: near-black
        assert _speed_to_color(100) == (30, 70, 230)  # blue
        assert _speed_to_color(200) == (20, 210, 210)  # cyan
        assert _speed_to_color(300) == (40, 220, 50)  # green
        assert _speed_to_color(400) == (235, 220, 40)  # yellow
        assert _speed_to_color(500) == (240, 40, 30)  # red

    def test_interpolates_linearly_between_anchors(self):
        assert _speed_to_color(50) == (20, 42, 130)  # halfway near-black -> blue
        assert _speed_to_color(150) == (25, 140, 220)  # halfway blue -> cyan

    def test_clamps_above_top_anchor_to_red(self):
        assert _speed_to_color(501) == (240, 40, 30)
        assert _speed_to_color(10_000) == (240, 40, 30)


class TestBuildHeatmap:
    def test_empty_window_returns_empty(self):
        fs = Funscript(actions=[(0, 0), (1000, 100)])

        assert build_heatmap(fs, 10, start_ms=0, end_ms=0) == []

    def test_empty_and_single_action_scripts_are_all_near_black(self):
        assert build_heatmap(Funscript(actions=[]), 4, start_ms=0, end_ms=10_000) == [_NEAR_BLACK] * 4
        assert build_heatmap(Funscript(actions=[(500, 80)]), 4, start_ms=0, end_ms=10_000) == [_NEAR_BLACK] * 4

    def test_full_stroke_per_bin_reads_as_100_units_per_second(self):
        fs = Funscript(actions=[(0, 0), (1000, 100), (2000, 0), (3000, 100), (4000, 0)])

        assert build_heatmap(fs, 4, start_ms=0, end_ms=4000) == [_BLUE] * 4

    def test_segment_spanning_bins_splits_travel_by_overlap(self):
        # One 100-unit stroke across the whole 2s: 50 units land in each
        # 1s bin -> 50 units/s -> the halfway near-black->blue color.
        fs = Funscript(actions=[(0, 0), (2000, 100)])

        assert build_heatmap(fs, 2, start_ms=0, end_ms=2000) == [(20, 42, 130)] * 2

    def test_bins_outside_the_scripted_range_are_near_black(self):
        # Activity only in bin 1: bins before the first action and after
        # the last stay idle-colored.
        fs = Funscript(actions=[(1000, 0), (1500, 100), (2000, 0)])

        colors = build_heatmap(fs, 4, start_ms=0, end_ms=4000)

        assert colors[0] == _NEAR_BLACK
        assert colors[1] == (20, 210, 210)  # 200 units over 1s -> cyan
        assert colors[2] == _NEAR_BLACK
        assert colors[3] == _NEAR_BLACK

    def test_zero_length_segment_is_ignored(self):
        # Duplicate timestamps happen in real scripts; an instantaneous
        # jump has no duration to average over and must not divide by zero.
        fs = Funscript(actions=[(0, 0), (1000, 100), (1000, 20), (2000, 120)])

        assert build_heatmap(fs, 2, start_ms=0, end_ms=2000) == [_BLUE, _BLUE]

    def test_single_bucket_averages_the_whole_video(self):
        # 100 units of travel in the first second, idle second second:
        # averaged over the one 2s bin -> 50 units/s.
        fs = Funscript(actions=[(0, 0), (1000, 100)])

        assert build_heatmap(fs, 1, start_ms=0, end_ms=2000) == [(20, 42, 130)]

    def test_actions_past_the_video_end_only_count_in_range_travel(self):
        # Half of the 100-unit stroke happens after the video ends; the
        # single 1s bin sees 50 units -> 50 units/s.
        fs = Funscript(actions=[(0, 0), (2000, 100)])

        assert build_heatmap(fs, 1, start_ms=0, end_ms=1000) == [(20, 42, 130)]


class TestBuildHeatmapWindow:
    def test_sub_range_buckets_only_see_their_window(self):
        # Full strokes at 100 units/s throughout: a [1000, 3000] window
        # split into two 1s bins reads blue in each.
        fs = Funscript(actions=[(0, 0), (1000, 100), (2000, 0), (3000, 100), (4000, 0)])

        assert build_heatmap(fs, 2, start_ms=1000, end_ms=3000) == [_BLUE] * 2

    def test_activity_entirely_before_the_window_is_excluded(self):
        fs = Funscript(actions=[(0, 0), (1000, 100)])

        assert build_heatmap(fs, 2, start_ms=2000, end_ms=4000) == [_NEAR_BLACK] * 2

    def test_segment_straddling_the_window_start_counts_only_the_overlap(self):
        # Stroke spans [500, 1500]; the window sees its second half: 50
        # units land in the single 1s bin -> 50 units/s.
        fs = Funscript(actions=[(500, 0), (1500, 100)])

        assert build_heatmap(fs, 1, start_ms=1000, end_ms=2000) == [(20, 42, 130)]
