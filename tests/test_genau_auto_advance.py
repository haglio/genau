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


def _run(state, *, playing=True, seconds=30.0, step=0.1, start=0.0):
    """Tick from *start* for *seconds*, returning the deltas passed to step_clip."""
    calls: list[int] = []
    tick_auto_advance(state, start, playing=playing, step_clip=calls.append)
    for i in range(int(seconds / step)):
        tick_auto_advance(
            state, start + step * (i + 1), playing=playing, step_clip=calls.append,
        )
    return calls


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
