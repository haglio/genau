from __future__ import annotations

import bisect
import json
from dataclasses import dataclass
from pathlib import Path


_BASE_THRESHOLD = 95
_MIN_LOOP_MS = 500

# A funscript whose sustained action does not begin until at least this far in
# has a long enough quiet lead-in that the OSR2 should rest at its parked
# position rather than drift toward a still-distant action.  The same value
# doubles as the gap that marks a leading action as an isolated stray blip:
# real action is densely sampled, so the first action closely followed by
# another (gap below this) is where it truly begins.
_QUIET_LEAD_IN_MS = 5000


@dataclass
class Funscript:
    actions: list[tuple[int, int]]

    def __post_init__(self) -> None:
        self._times = [a[0] for a in self.actions]
        self._first_real_event_ms = self._compute_first_real_event_ms()
        self._dense_times = self._compute_dense_times()

    @property
    def first_real_event_ms(self) -> int | None:
        """Onset of sustained action past a long quiet lead-in, else None.

        Returns the time of the first action that is closely followed by
        another (i.e. where dense action begins), skipping any isolated stray
        blips at the very start.  Returns None when action begins promptly, so
        callers drive from the top; otherwise the OSR2 rests at its parked
        position until this time.
        """
        return self._first_real_event_ms

    def _compute_first_real_event_ms(self) -> int | None:
        for (t, _p), (next_t, _np) in zip(self.actions, self.actions[1:]):
            if next_t - t < _QUIET_LEAD_IN_MS:
                return t if t >= _QUIET_LEAD_IN_MS else None
        return None

    def _compute_dense_times(self) -> list[int]:
        """Times of actions that belong to a dense cluster — those with a
        neighbour within _QUIET_LEAD_IN_MS.  Isolated stray blips are excluded,
        the same standard first_real_event_ms uses to find where action begins.
        """
        dense: list[int] = []
        for k, (t, _p) in enumerate(self.actions):
            prev_close = k > 0 and t - self.actions[k - 1][0] < _QUIET_LEAD_IN_MS
            next_close = (
                k + 1 < len(self.actions)
                and self.actions[k + 1][0] - t < _QUIET_LEAD_IN_MS
            )
            if prev_close or next_close:
                dense.append(t)
        return dense

    def is_resting_at(self, position_ms: int) -> bool:
        """True when position_ms sits in a quiet stretch — no dense action
        within _QUIET_LEAD_IN_MS on either side (a funscript's lead-in or an
        interior gap).  In Hybrid the orchestrator hands these stretches to
        Genau; scripted stretches (not resting) drive the OSR2 from the
        funscript, and the buffer lets the script reclaim control before its
        next action fires.
        """
        if not self._dense_times:
            return True
        i = bisect.bisect_left(self._dense_times, position_ms)
        nearest = min(
            abs(self._dense_times[j] - position_ms)
            for j in (i - 1, i)
            if 0 <= j < len(self._dense_times)
        )
        return nearest > _QUIET_LEAD_IN_MS


def snap_loop(
    fs: Funscript | None,
    in_ms: int,
    out_ms: int,
    threshold: int = _BASE_THRESHOLD,
) -> tuple[int, int]:
    if fs is None or not fs.actions:
        # No funscript to snap to (a plain clip loop): use the raw marked range,
        # ordered and widened to the minimum loop length.
        lo, hi = min(in_ms, out_ms), max(in_ms, out_ms)
        return lo, max(hi, lo + _MIN_LOOP_MS)
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
