"""A boolean two parts of the app share, and the edge that belongs with it."""
from __future__ import annotations

from genau.flags import Flag


class TestTheValue:
    def test_it_starts_off_unless_told_otherwise(self):
        assert Flag().on is False
        assert Flag(on=True).on is True

    def test_it_is_moved_by_writing_to_it(self):
        flag = Flag()

        flag.on = True

        assert flag.on is True


class TestTheEdge:
    """Turning the HUD on rebuilds the window, so it has to happen on the change
    and not on every frame that finds the flag set."""

    def test_a_flag_that_has_not_moved_reports_nothing(self):
        assert Flag().moved() is False

    def test_a_flag_built_already_on_has_not_just_moved(self):
        """Otherwise the first tick of a session rebuilds a window nobody
        asked it to."""
        assert Flag(on=True).moved() is False

    def test_a_move_is_reported_once(self):
        flag = Flag()
        flag.on = True

        assert flag.moved() is True
        assert flag.moved() is False

    def test_moving_back_is_a_move_too(self):
        flag = Flag()
        flag.on = True
        flag.moved()

        flag.on = False

        assert flag.moved() is True

    def test_a_move_and_a_move_back_before_anyone_asks_is_no_move(self):
        """The flag is what it was; there is nothing to act on."""
        flag = Flag()

        flag.on = True
        flag.on = False

        assert flag.moved() is False

    def test_two_flags_do_not_share_their_edge(self):
        one, other = Flag(), Flag()
        one.on = True

        assert one.moved() is True
        assert other.moved() is False
