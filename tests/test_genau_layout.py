from __future__ import annotations

import pytest

from genau.layout import compute_video_rects


class TestLandscapeVideo:
    def test_wider_video_letterboxed_vertically(self):
        """16:9 video in 4:3 window -> full width, bars top/bottom."""
        rects = compute_video_rects(1920, 1080, 1200, 900)

        assert len(rects) == 1
        x, y, w, h = rects[0]
        assert w == 1200
        assert h == 675  # 1200 * (1080/1920)
        assert x == 0
        assert y == 112  # (900 - 675) // 2

    def test_narrower_video_pillarboxed(self):
        """4:3 video in 16:9 window -> full height, bars left/right."""
        rects = compute_video_rects(800, 600, 1600, 900)

        assert len(rects) == 1
        x, y, w, h = rects[0]
        assert h == 900
        assert w == 1200  # 800 * (900/600)
        assert x == 200  # (1600 - 1200) // 2
        assert y == 0


class TestPortraitVideo:
    def test_portrait_tiles_twice(self):
        """9:16 portrait in a wide window -> 2 tiles side by side."""
        rects = compute_video_rects(1080, 1920, 1200, 900)

        assert len(rects) == 2
        # Each tile fills window height, aspect preserved
        tile_w = int(1080 * (900 / 1920))  # 506
        tile_h = 900
        for _, _, w, h in rects:
            assert w == tile_w
            assert h == tile_h
        # Tiles centered as a group
        total_w = tile_w * 2
        margin = (1200 - total_w) // 2
        assert rects[0][0] == margin
        assert rects[1][0] == margin + tile_w

    def test_narrow_portrait_tiles_many(self):
        """Very narrow portrait -> many tiles."""
        # 270x480 in 1200x900 -> tile_w = 270*(900/480) = 506, tiles = 2
        # 200x800 in 1200x900 -> tile_w = 200*(900/800) = 225, tiles = 5
        rects = compute_video_rects(200, 800, 1200, 900)

        assert len(rects) == 5
        tile_w = int(200 * (900 / 800))  # 225
        for _, _, w, h in rects:
            assert w == tile_w
            assert h == 900

    def test_single_portrait_when_tile_too_wide(self):
        """Nearly-square portrait only fits once -> single centered rect."""
        # 700x800 in 1200x900 -> tile_w = 700*(900/800) = 787, tiles = 1
        rects = compute_video_rects(700, 800, 1200, 900)

        assert len(rects) == 1
        x, y, w, h = rects[0]
        assert w == int(700 * (900 / 800))
        assert h == 900


class TestEdgeCases:
    def test_exact_fit_no_bars(self):
        """Video matches window aspect exactly."""
        rects = compute_video_rects(1200, 900, 1200, 900)

        assert len(rects) == 1
        assert rects[0] == (0, 0, 1200, 900)

    def test_square_video_centered(self):
        """Square video in wider window -> pillarboxed."""
        rects = compute_video_rects(500, 500, 1200, 900)

        assert len(rects) == 1
        x, y, w, h = rects[0]
        assert w == 900
        assert h == 900
        assert x == 150  # (1200 - 900) // 2
        assert y == 0
