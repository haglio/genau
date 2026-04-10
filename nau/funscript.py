from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Funscript:
    actions: list[tuple[int, int]]

    def __post_init__(self) -> None:
        self._times = [a[0] for a in self.actions]


_BASE_THRESHOLD = 95
_MIN_LOOP_MS = 500


def snap_loop(
    fs: Funscript,
    in_ms: int,
    out_ms: int,
    threshold: int = _BASE_THRESHOLD,
) -> tuple[int, int]:
    bases = [t for t, p in fs.actions if p >= threshold]
    snapped_in = in_ms
    for t in reversed(bases):
        if t <= in_ms:
            snapped_in = t
            break
    else:
        snapped_in = fs.actions[0][0]

    snapped_out = out_ms
    for t in bases:
        if t >= out_ms:
            snapped_out = t
            break
    else:
        snapped_out = fs.actions[-1][0]

    if snapped_out - snapped_in < _MIN_LOOP_MS:
        for t in bases:
            if t > snapped_in:
                snapped_out = t
                break
    if snapped_out - snapped_in < _MIN_LOOP_MS:
        snapped_out = snapped_in + _MIN_LOOP_MS

    return snapped_in, snapped_out


def load(path: Path) -> Funscript:
    data = json.loads(path.read_text())
    raw = data["actions"]
    actions = sorted(((a["at"], a["pos"]) for a in raw), key=lambda a: a[0])
    return Funscript(actions=actions)
