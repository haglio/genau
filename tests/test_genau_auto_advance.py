from __future__ import annotations

import random

from genau.auto_advance import (
    AutoAdvanceState,
    disable_auto_advance,
    enable_auto_advance,
    tick_auto_advance,
    toggle_auto_advance,
    toggle_clip_lock,
)


def _run(state, *, playing=True, seconds=30.0, step=0.1, start=0.0, on_screen="clip"):
    """Tick from *start* for *seconds* with one clip steady on screen.

    Returns the deltas passed to step_clip.  A steady clip is the common case;
    the load-stacking tests below drive the on-screen clip themselves.
    """
    calls: list[int] = []
    tick_auto_advance(
        state, start, playing=playing, on_screen_clip=on_screen, step_clip=calls.append,
    )
    for i in range(int(seconds / step)):
        tick_auto_advance(
            state, start + step * (i + 1),
            playing=playing, on_screen_clip=on_screen, step_clip=calls.append,
        )
    return calls


def _series(state, start, stop, on_screen, *, playing=True, step=0.1):
    """Tick across [start, stop] with *on_screen* the clip showing throughout.

    Returns the ``now`` of each fire, so a test can assert *when* it advanced.
    """
    fires: list[float] = []
    n = int(round((stop - start) / step))
    for i in range(n + 1):
        now = round(start + step * i, 3)
        tick_auto_advance(
            state, now, playing=playing, on_screen_clip=on_screen,
            step_clip=lambda _delta, _now=now: fires.append(_now),
        )
    return fires


class TestTickAutoAdvance:
    def test_advances_clip_after_the_default_interval(self):
        state = AutoAdvanceState(active=True, rng=random.Random(42))
        assert _run(state, seconds=13.0) == [1]

    def test_holds_the_clip_while_the_room_is_paused(self):
        state = AutoAdvanceState(active=True, rng=random.Random(42))
        assert _run(state, playing=False, seconds=60.0) == []

    def test_a_pause_banks_no_time_toward_the_next_switch(self):
        state = AutoAdvanceState(active=True, interval=10.0)
        assert _run(state, seconds=4.0) == []
        # However long the room sits paused, resuming owes the remaining 6s.
        assert _run(state, playing=False, seconds=600.0, start=4.0) == []
        assert _run(state, seconds=5.0, start=604.0) == []
        assert _run(state, seconds=2.0, start=609.0) == [1]

    def test_a_locked_clip_holds_the_screen(self):
        state = AutoAdvanceState(active=True, locked=True, rng=random.Random(42))
        assert _run(state, seconds=60.0) == []


class TestAutoAdvanceMeasuresTheClipOnScreen:
    """The interval is timed from the clip that is playing, not the request.

    Genau can take seconds to decode a clip; timing from the request would let a
    short interval fire over and over while the first switch was still loading.
    """

    def test_a_never_arriving_load_advances_only_once(self):
        # The clip we advance to never reaches the screen (slow/failed decode).
        # Auto-advance must ask once and then wait — not stack a fresh request
        # every interval.
        state = AutoAdvanceState(active=True, interval=3.0)
        fires = _series(state, 0.0, 30.0, "A")
        assert len(fires) == 1

    def test_the_interval_restarts_when_the_new_clip_arrives(self):
        state = AutoAdvanceState(active=True, interval=3.0)
        fires = _series(state, 0.0, 5.0, "A")          # A shown from t=0
        fires += _series(state, 5.1, 12.0, "B")        # B arrives at t=5.1
        assert len(fires) == 2
        assert 2.9 <= fires[0] <= 3.2                  # ~3s into A
        assert 8.0 <= fires[1] <= 8.4                  # ~3s after B arrived

    def test_counting_starts_only_once_a_clip_is_on_screen(self):
        state = AutoAdvanceState(active=True, interval=3.0)
        fires = _series(state, 0.0, 4.0, None)         # still decoding — nothing shown
        fires += _series(state, 4.1, 9.0, "A")         # A finally appears at t=4.1
        assert len(fires) == 1
        assert 6.9 <= fires[0] <= 7.4                  # ~3s after A appeared, not after t=0


class TestArmingAutoAdvance:
    def test_toggle_flips_active(self):
        state = AutoAdvanceState()
        toggle_auto_advance(state)
        assert state.active is True
        toggle_auto_advance(state)
        assert state.active is False

    def test_toggle_keeps_a_named_interval(self):
        state = AutoAdvanceState(active=True, interval=30.0)
        toggle_auto_advance(state)
        toggle_auto_advance(state)
        assert state.interval == 30.0

    def test_enable_without_an_interval_leaves_the_default(self):
        state = AutoAdvanceState()
        enable_auto_advance(state)
        assert state.active is True
        assert state.interval is None

    def test_enable_with_an_interval_names_the_seconds(self):
        state = AutoAdvanceState()
        enable_auto_advance(state, interval=30.0)
        assert state.active is True
        assert state.interval == 30.0

    def test_re_arming_starts_the_interval_fresh_on_the_current_clip(self):
        # Fire once so the state is left "awaiting" a switch that never comes,
        # then disable and re-enable: the clip is still on screen, and arming
        # must count it afresh rather than sit forever waiting on the old
        # request.
        state = AutoAdvanceState(active=True, interval=3.0)
        assert len(_series(state, 0.0, 4.0, "A")) == 1
        disable_auto_advance(state)
        enable_auto_advance(state)
        assert len(_series(state, 4.0, 8.0, "A")) == 1

    def test_disable_releases_the_lock(self):
        # The lock is a hold *within* auto-advance, so disarming clears it —
        # otherwise re-arming would sit on a clip nobody remembers locking.
        state = AutoAdvanceState(active=True, locked=True)
        disable_auto_advance(state)
        assert state.active is False
        assert state.locked is False

    def test_toggle_clip_lock_flips_the_lock(self):
        state = AutoAdvanceState(active=True)
        toggle_clip_lock(state)
        assert state.locked is True
        toggle_clip_lock(state)
        assert state.locked is False
