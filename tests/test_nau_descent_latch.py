"""The forecasts a trace is holding: one choice per approaching turn.

A descent's top and touch-down are chosen once for the turn they belong to and
then held.  Holding them means having somewhere to hold them, and this is that
place: the three modules that used to pass one bare dict around -- :mod:`nau.drive_trace` writing it as it paints,
:mod:`nau.status` reading it as it publishes, :mod:`nau.drive_gate` voiding it
-- now share a type that names its own fields.

What each held choice MEANS, and when it stops being true, is
:mod:`nau.drive_trace`'s and :mod:`nau.drive_gate`'s to say and is tested
there.  Here is only the holding.
"""
from __future__ import annotations

from player_core.drive_readout import DriveHud

from nau.descent_latch import DescentChoice, DescentLatch, DriveKey

TURN_MS = 3_000
KEY = DriveKey(center=50, amplitude=100, speed=50, let_go=None)


def _choice(top: float = 0.35, touch: int | None = 3_600) -> DescentChoice:
    return DescentChoice(key=KEY, top=top, touch=touch)


class TestTheWaveAChoiceWasCutFrom:
    def test_a_key_is_the_four_fields_that_identify_a_wave(self):
        """Anything else about a publish moves every frame; these four move
        only when the stroke is really a different stroke."""
        publish = DriveHud(center=50, amplitude=100, speed=40, let_go=0.44)

        assert DriveKey.cut_from(publish) == DriveKey(
            center=50, amplitude=100, speed=40, let_go=0.44)


class TestWhatIsHeldForATurn:
    def test_a_remembered_choice_comes_back_for_its_turn(self):
        latch = DescentLatch()

        latch.remember(TURN_MS, _choice(), stale_before=0)

        assert latch.choice_for(TURN_MS) == _choice()

    def test_a_turn_nothing_was_chosen_for_holds_nothing(self):
        assert DescentLatch().choice_for(TURN_MS) is None

    def test_choosing_again_for_a_turn_replaces_what_was_held(self):
        """The wave realigned, so the old wave's answer is not carried."""
        latch = DescentLatch()
        latch.remember(TURN_MS, _choice(), stale_before=0)

        latch.remember(TURN_MS, _choice(top=0.5, touch=3_800), stale_before=0)

        assert latch.choice_for(TURN_MS) == _choice(top=0.5, touch=3_800)

    def test_voiding_leaves_nothing_held_for_any_turn(self):
        """What the gate does when the wave stops describing this approach."""
        latch = DescentLatch()
        latch.remember(TURN_MS, _choice(), stale_before=0)

        latch.void_all()

        assert latch.choice_for(TURN_MS) is None


class TestTurnsThePlayheadHasLeftBehind:
    """A session runs for hours and every turn it approaches leaves an entry,
    so the ones it is long past are dropped.  Only once there are enough to be
    worth scanning: this is housekeeping, not a rule about what is true, and a
    turn just behind the playhead is still the one a status read lands on.
    """

    CROWD = range(1_000, 18_000, 1_000)  # 17 turns: one more than it takes

    def test_a_turn_left_behind_goes_once_there_are_enough_to_scan(self):
        latch = DescentLatch()

        for turn in self.CROWD:
            latch.remember(turn, _choice(), stale_before=9_000)

        assert latch.choice_for(1_000) is None

    def test_the_turns_still_in_play_stay(self):
        latch = DescentLatch()

        for turn in self.CROWD:
            latch.remember(turn, _choice(), stale_before=9_000)

        assert latch.choice_for(9_000) == _choice()
        assert latch.choice_for(17_000) == _choice()

    def test_a_handful_of_turns_is_never_worth_scanning(self):
        """Nothing is dropped while the latch is small, so a long-held choice
        cannot go missing on a player that has only just started."""
        latch = DescentLatch()

        latch.remember(1_000, _choice(), stale_before=9_000)

        assert latch.choice_for(1_000) == _choice()
