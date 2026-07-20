from __future__ import annotations

import numpy as np

from nau.funscript import Funscript
from nau.heatmap import build_heatmap
from nau.overlay import (
    HeatmapStrip,
    ZoomWindow,
    time_to_x,
)


def _frame(fill: int, w: int = 160, h: int = 90) -> np.ndarray:
    return np.full((h, w, 3), fill, dtype=np.uint8)


def _funscript():
    return Funscript(actions=[(0, 0), (1000, 100), (2000, 0)])


class TestHeatmapStrip:
    def test_builds_one_color_per_pixel_of_width(self):
        fs = _funscript()
        strip = HeatmapStrip()

        strip.update("v0.mp4", fs, 4000.0, width=40)

        assert strip.colors == build_heatmap(fs, 40, start_ms=0, end_ms=4000.0)
        assert len(strip.colors) == 40
        assert strip.height == 24

    def test_unscripted_video_has_no_strip(self):
        strip = HeatmapStrip()

        strip.update("plain.mp4", None, 4000.0, width=40)

        assert strip.colors == []
        assert strip.height == 0

    def test_caches_until_the_video_changes(self):
        strip = HeatmapStrip()
        strip.update("v0.mp4", _funscript(), 4000.0, width=40)
        built = strip.colors

        # Same video key: not rebuilt even if a different funscript is passed.
        strip.update("v0.mp4", Funscript(actions=[]), 4000.0, width=40)
        assert strip.colors is built

        # New video key: rebuilt.
        strip.update("v1.mp4", Funscript(actions=[]), 4000.0, width=40)
        assert strip.colors != built

    def test_width_change_rebuilds(self):
        strip = HeatmapStrip()
        strip.update("v0.mp4", _funscript(), 4000.0, width=40)

        strip.update("v0.mp4", _funscript(), 4000.0, width=64)

        assert len(strip.colors) == 64

    def test_full_view_window_spans_the_video(self):
        strip = HeatmapStrip()

        strip.update("v0.mp4", _funscript(), 4000.0, width=40)

        assert strip.window == (0.0, 4000.0)
        assert strip.record_in_ms is None

    def test_recording_zooms_into_a_taller_strip_around_the_in_point(self):
        fs = _funscript()
        strip = HeatmapStrip()

        strip.update(
            "v0.mp4", fs, 600_000.0, width=40,
            loop_state="recording", record_in_ms=50_000, position_ms=50_000.0,
        )

        assert strip.window == (48_000, 70_000)
        assert strip.height == 48
        assert strip.record_in_ms == 50_000
        assert strip.colors == build_heatmap(fs, 40, start_ms=48_000, end_ms=70_000)

    def test_recording_view_rescales_in_steps_not_continuously(self):
        strip = HeatmapStrip()

        def update(position_ms):
            strip.update(
                "v0.mp4", _funscript(), 600_000.0, width=40,
                loop_state="recording", record_in_ms=50_000, position_ms=position_ms,
            )

        update(50_000.0)
        held = strip.colors
        update(60_000.0)  # inside 85%: window and colors untouched
        assert strip.window == (48_000, 70_000)
        assert strip.colors is held

        update(66_800.0)  # past 85%: window doubles, colors rebuilt
        assert strip.window == (46_000, 90_000)
        assert strip.colors is not held

    def test_leaving_recording_restores_the_full_view(self):
        fs = _funscript()
        strip = HeatmapStrip()
        strip.update(
            "v0.mp4", fs, 600_000.0, width=40,
            loop_state="recording", record_in_ms=50_000, position_ms=66_800.0,
        )

        strip.update("v0.mp4", fs, 600_000.0, width=40, loop_state="looping")

        assert strip.window == (0.0, 600_000.0)
        assert strip.height == 24
        assert strip.record_in_ms is None
        assert strip.colors == build_heatmap(fs, 40, start_ms=0, end_ms=600_000.0)

        # A later recording zooms afresh from its own in point.
        strip.update(
            "v0.mp4", fs, 600_000.0, width=40,
            loop_state="recording", record_in_ms=100_000, position_ms=100_000.0,
        )
        assert strip.window == (98_000, 120_000)


class TestTimeToX:
    def test_maps_window_fraction_to_pixel(self):
        assert time_to_x(0, 0, 10_000, 100) == 0
        assert time_to_x(5_000, 0, 10_000, 100) == 50
        assert time_to_x(30_000, 20_000, 40_000, 100) == 50

    def test_clamps_to_the_strip(self):
        assert time_to_x(10_000, 0, 10_000, 100) == 99  # window end stays visible
        assert time_to_x(50_000, 20_000, 40_000, 100) == 99
        assert time_to_x(0, 20_000, 40_000, 100) == 0

    def test_empty_window_pins_left(self):
        assert time_to_x(500, 0, 0, 100) == 0


class TestZoomWindow:
    def test_initial_window_spans_20s_with_a_10_percent_lead(self):
        zoom = ZoomWindow(in_ms=50_000)

        assert zoom.bounds == (48_000, 70_000)  # 2s lead before the in point

    def test_holds_while_playhead_is_before_85_percent(self):
        zoom = ZoomWindow(in_ms=50_000)

        zoom.update(66_000)  # grow point is 48_000 + 0.85 * 22_000 = 66_700

        assert zoom.bounds == (48_000, 70_000)

    def test_doubles_span_once_playhead_passes_85_percent(self):
        zoom = ZoomWindow(in_ms=50_000)

        zoom.update(66_800)

        assert zoom.bounds == (46_000, 90_000)  # span 40s, lead 4s

    def test_far_jump_catches_up_in_doubling_steps(self):
        zoom = ZoomWindow(in_ms=50_000)

        zoom.update(200_000)  # e.g. a seek while recording

        assert zoom.bounds == (18_000, 370_000)  # span doubled 20s -> 320s



def _rgba(bar, y, x):
    px = bar[y, x]
    return int(px[2]), int(px[1]), int(px[0]), int(px[3])


# The plain scrubber and its track geometry moved to player_core.timeline —
# tested there (tests/test_timeline.py).  What stays here is Nau's own funscript
# heatmap, which builds on that shared frame.


class TestHeatmapBgra:
    def _framed_strip(self, win_w=200):
        # Production builds the colour row at the inset track width, then frames
        # it to full window width.
        from nau.overlay import bar_track_x, heatmap_bgra
        x0, x1 = bar_track_x(win_w)
        strip = HeatmapStrip()
        strip.update("v.mp4", _funscript(), 4000.0, width=x1 - x0)  # window 0..4000
        return heatmap_bgra(strip, 2000, (1000, 3000), win_w), x0, x1

    def test_strip_is_inset_from_the_window_edges(self):
        bgra, x0, x1 = self._framed_strip()
        my = bgra.shape[0] // 2
        assert bgra[my, 5, 3] == 0 and bgra[my, 195, 3] == 0   # nothing at the edges
        assert bgra[my, (x0 + x1) // 2, 3] > 0                 # painted in the track

    def test_has_a_two_tone_border(self):
        from player_core.timeline import BAR_INSET_Y as _BAR_INSET_Y
        bgra, x0, x1 = self._framed_strip()
        outer = _rgba(bgra, _BAR_INSET_Y, x0 + 10)      # dark outer edge (away from marks)
        inner = _rgba(bgra, _BAR_INSET_Y + 1, x0 + 10)  # light inner border
        assert max(outer[:3]) < 100
        assert min(inner[:3]) >= 200 and inner[3] >= 200

    def test_prominent_full_height_marks(self):
        bgra, x0, x1 = self._framed_strip()
        my = bgra.shape[0] // 2
        cx = x0 + (x1 - x0) // 2
        assert _rgba(bgra, my, cx) == (255, 255, 255, 255)     # white playcursor @50%
        white = [x for x in range(x0, x1) if _rgba(bgra, my, x) == (255, 255, 255, 255)]
        assert len(white) >= 3                                 # 3px, not a hairline
        amber = [x for x in range(x0, x1) if _rgba(bgra, my, x)[:3] == (235, 180, 60)]
        assert amber and any(x < cx for x in amber) and any(x > cx for x in amber)

    def test_unscripted_strip_is_none(self):
        from nau.overlay import heatmap_bgra
        strip = HeatmapStrip()
        strip.update("plain.mp4", None, 4000.0, width=100)
        assert heatmap_bgra(strip, 0, None, 100) is None


class TestLoopThumbCapture:
    def test_asks_for_in_first_then_out_near_end(self):
        from nau.overlay import LoopThumbCapture
        cap = LoopThumbCapture()

        assert cap.needed("looping", (2000, 4000), 2000) == "in"
        cap.set("in", object())
        assert cap.needed("looping", (2000, 4000), 2500) is None  # not near out yet
        assert cap.needed("looping", (2000, 4000), 3700) == "out"  # within 400ms of 4000
        cap.set("out", object())
        assert cap.needed("looping", (2000, 4000), 3900) is None

    def test_clears_when_loop_ends(self):
        from nau.overlay import LoopThumbCapture
        cap = LoopThumbCapture()
        cap.needed("looping", (2000, 4000), 2000)
        cap.set("in", object())

        assert cap.needed("normal", None, 0) is None
        assert cap.in_thumb is None

    def test_reset_thumbs_on_new_loop_bounds(self):
        from nau.overlay import LoopThumbCapture
        cap = LoopThumbCapture()
        cap.needed("looping", (2000, 4000), 2000)
        cap.set("in", object())

        # a different loop → in_thumb must be re-requested
        assert cap.needed("looping", (5000, 7000), 5000) == "in"


class TestLabelXsReadded:
    def test_centers_and_avoids_overlap(self):
        from nau.overlay import label_xs
        assert label_xs(100, 500, 60, 60, 1000) == (70, 470)
        ix, ox = label_xs(100, 120, 60, 60, 1000)  # markers close
        assert ox >= ix + 60
