from __future__ import annotations

from genau.clip_advance import (
    DEFAULT_INTERVAL_S,
    MAX_INTERVAL_S,
    MIN_INTERVAL_S,
    ClipAdvanceState,
    adjust_interval,
    set_interval,
    set_locked,
    tick_clip_advance,
    toggle_lock,
)


def _run(state, *, playing=True, seconds=30.0, step=0.1, start=0.0, on_screen="clip"):
    """Tick from *start* for *seconds* with one clip steady on screen.

    Returns the deltas passed to step_clip.  A steady clip is the common case;
    the load-stacking tests below drive the on-screen clip themselves.
    """
    calls: list[int] = []
    tick_clip_advance(
        state, start, playing=playing, on_screen_clip=on_screen, step_clip=calls.append,
    )
    for i in range(int(seconds / step)):
        tick_clip_advance(
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
        tick_clip_advance(
            state, now, playing=playing, on_screen_clip=on_screen,
            step_clip=lambda _delta, _now=now: fires.append(_now),
        )
    return fires


class TestTickClipAdvance:
    def test_a_new_state_holds_its_clip(self):
        """Locked is where Genau opens — a clip repeating, nothing moving on its
        own — which is what an unarmed auto-advance used to give."""
        assert ClipAdvanceState().locked is True
        assert _run(ClipAdvanceState(), seconds=60.0) == []

    def test_unlocked_it_advances_after_the_interval(self):
        state = ClipAdvanceState(locked=False)
        assert _run(state, seconds=DEFAULT_INTERVAL_S + 3.0) == [1]

    def test_holds_the_clip_while_the_room_is_paused(self):
        assert _run(ClipAdvanceState(locked=False), playing=False, seconds=60.0) == []

    def test_a_pause_banks_no_time_toward_the_next_switch(self):
        state = ClipAdvanceState(locked=False, interval=10)
        assert _run(state, seconds=4.0) == []
        # However long the room sits paused, resuming owes the remaining 6s.
        assert _run(state, playing=False, seconds=600.0, start=4.0) == []
        assert _run(state, seconds=5.0, start=604.0) == []
        assert _run(state, seconds=2.0, start=609.0) == [1]

    def test_locking_mid_interval_stops_the_clock(self):
        state = ClipAdvanceState(locked=False, interval=5)
        assert _run(state, seconds=3.0) == []
        set_locked(state, True)
        assert _run(state, seconds=60.0, start=3.0) == []


class TestAdvanceMeasuresTheClipOnScreen:
    """The interval is timed from the clip that is playing, not the request.

    Genau can take seconds to decode a clip; timing from the request would let a
    short interval fire over and over while the first switch was still loading.
    """

    def test_a_never_arriving_load_advances_only_once(self):
        # The clip we advance to never reaches the screen (slow/failed decode).
        # It must ask once and then wait — not stack a fresh request every
        # interval.
        state = ClipAdvanceState(locked=False, interval=3)
        fires = _series(state, 0.0, 30.0, "A")
        assert len(fires) == 1

    def test_the_interval_restarts_when_the_new_clip_arrives(self):
        state = ClipAdvanceState(locked=False, interval=3)
        fires = _series(state, 0.0, 5.0, "A")          # A shown from t=0
        fires += _series(state, 5.1, 12.0, "B")        # B arrives at t=5.1
        assert len(fires) == 2
        assert 2.9 <= fires[0] <= 3.2                  # ~3s into A
        assert 8.0 <= fires[1] <= 8.4                  # ~3s after B arrived

    def test_counting_starts_only_once_a_clip_is_on_screen(self):
        state = ClipAdvanceState(locked=False, interval=3)
        fires = _series(state, 0.0, 4.0, None)         # still decoding — nothing shown
        fires += _series(state, 4.1, 9.0, "A")         # A finally appears at t=4.1
        assert len(fires) == 1
        assert 6.9 <= fires[0] <= 7.4                  # ~3s after A appeared, not after t=0


class TestTheLock:
    def test_toggle_flips_it(self):
        state = ClipAdvanceState()
        toggle_lock(state)
        assert state.locked is False
        toggle_lock(state)
        assert state.locked is True

    def test_unlocking_starts_the_interval_fresh_on_the_clip_on_screen(self):
        # Fire once so the state is left "awaiting" a switch that never comes,
        # then lock and unlock: the clip is still on screen, and the release must
        # count it afresh rather than sit forever waiting on the old request.
        state = ClipAdvanceState(locked=False, interval=3)
        assert len(_series(state, 0.0, 4.0, "A")) == 1
        set_locked(state, True)
        set_locked(state, False)
        assert len(_series(state, 4.0, 8.0, "A")) == 1

    def test_the_pace_survives_a_lock(self):
        state = ClipAdvanceState(locked=False, interval=30)
        toggle_lock(state)
        toggle_lock(state)
        assert state.interval == 30


class TestTheInterval:
    def test_it_opens_on_the_default(self):
        assert ClipAdvanceState().interval == DEFAULT_INTERVAL_S

    def test_it_is_clamped_to_the_usable_range(self):
        state = ClipAdvanceState()
        set_interval(state, 0)
        assert state.interval == MIN_INTERVAL_S
        set_interval(state, 9999)
        assert state.interval == MAX_INTERVAL_S

    def test_the_arrows_stop_at_the_ends_rather_than_wrapping(self):
        state = ClipAdvanceState(interval=MIN_INTERVAL_S)
        adjust_interval(state, -1)
        assert state.interval == MIN_INTERVAL_S

        state = ClipAdvanceState(interval=MAX_INTERVAL_S)
        adjust_interval(state, 1)
        assert state.interval == MAX_INTERVAL_S
