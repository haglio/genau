from __future__ import annotations


def compute_video_rects(
    video_w: int,
    video_h: int,
    window_w: int,
    window_h: int,
) -> list[tuple[int, int, int, int]]:
    """Return ``(x, y, w, h)`` destination rectangles for displaying a video.

    Preserves the video's aspect ratio.  Landscape (or square) videos
    produce a single centered rectangle.  Portrait videos are tiled
    horizontally as many times as they fit.
    """
    is_portrait = video_h > video_w

    # Scale to fit window height
    tile_h = window_h
    tile_w = int(video_w * (window_h / video_h))

    if is_portrait:
        tile_count = max(1, window_w // tile_w)
    else:
        if tile_w > window_w:
            # Wider than window — fit by width instead
            tile_w = window_w
            tile_h = int(video_h * (window_w / video_w))
        tile_count = 1

    total_w = tile_w * tile_count
    margin = (window_w - total_w) // 2
    y = (window_h - tile_h) // 2
    return [(margin + i * tile_w, y, tile_w, tile_h) for i in range(tile_count)]
