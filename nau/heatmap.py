"""Funscript activity heatmap: average stroke speed per time bucket -> color.

Pure logic, no pygame: build_heatmap turns a Funscript into one color per
horizontal pixel of the strip; overlay.py owns the drawing.
"""
from __future__ import annotations

from player_core.funscript import Funscript

# Anchor colors for the classic funscript-heatmap feel: idle bins read as
# near-black, then blue -> cyan -> green -> yellow -> red as the average
# stroke speed (0-100 position units per second) climbs to 500.
_GRADIENT: list[tuple[float, tuple[int, int, int]]] = [
    (0.0, (10, 14, 30)),
    (100.0, (30, 70, 230)),
    (200.0, (20, 210, 210)),
    (300.0, (40, 220, 50)),
    (400.0, (235, 220, 40)),
    (500.0, (240, 40, 30)),
]


def _speed_to_color(speed: float) -> tuple[int, int, int]:
    for (s0, c0), (s1, c1) in zip(_GRADIENT, _GRADIENT[1:]):
        if speed <= s1:
            frac = (speed - s0) / (s1 - s0)
            return tuple(round(lo + (hi - lo) * frac) for lo, hi in zip(c0, c1))
    return _GRADIENT[-1][1]


def build_heatmap(
    fs: Funscript, buckets: int, *, start_ms: float, end_ms: float,
) -> list[tuple[int, int, int]]:
    """One color per equal bin of [start_ms, end_ms], by average stroke speed.

    Each action segment spreads its |pos delta| over the bins it overlaps,
    proportional to the overlap; a bin's speed is its accumulated travel
    divided by the bin length in seconds. Bins nothing overlaps (gaps,
    activity outside the window) stay at the idle color. The full-video
    strip is simply the [0, duration] window.
    """
    if end_ms <= start_ms:
        return []
    bin_ms = (end_ms - start_ms) / buckets
    travel = [0.0] * buckets  # position units traveled inside each bin
    for (t0, p0), (t1, p1) in zip(fs.actions, fs.actions[1:]):
        if t1 <= t0:
            continue
        delta = abs(p1 - p0)
        first = max(0, int((t0 - start_ms) // bin_ms))
        last = min(buckets - 1, int((t1 - start_ms) // bin_ms))
        for b in range(first, last + 1):
            bin_start = start_ms + b * bin_ms
            overlap_ms = min(t1, bin_start + bin_ms) - max(t0, bin_start)
            travel[b] += delta * overlap_ms / (t1 - t0)
    bin_s = bin_ms / 1000.0
    return [_speed_to_color(units / bin_s) for units in travel]
