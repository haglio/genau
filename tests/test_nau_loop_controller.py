from __future__ import annotations

from nau.funscript import Funscript
from nau.loop_controller import LoopController, LoopState


def _make_fs():
    return Funscript(actions=[
        (0, 100), (1000, 0), (2000, 100), (3000, 0),
        (4000, 100), (5000, 0), (6000, 100),
    ])


class TestLoopController:
    def test_initial_state_is_normal(self):
        lc = LoopController(_make_fs())

        assert lc.state == LoopState.NORMAL

    def test_space_down_normal_transitions_to_marking(self):
        lc = LoopController(_make_fs())

        lc.on_space_down(2500)

        assert lc.state == LoopState.MARKING
        assert lc.in_ms == 2500

    def test_space_up_marking_transitions_to_looping_with_snapped_bounds(self):
        lc = LoopController(_make_fs())
        lc.on_space_down(2500)

        lc.on_space_up(3500)

        assert lc.state == LoopState.LOOPING
        assert lc.in_ms == 2000
        assert lc.out_ms == 4000

    def test_space_down_looping_transitions_to_normal(self):
        lc = LoopController(_make_fs())
        lc.on_space_down(2500)
        lc.on_space_up(3500)

        lc.on_space_down(3000)

        assert lc.state == LoopState.NORMAL
        assert lc.in_ms is None
        assert lc.out_ms is None

    def test_check_loop_returns_none_when_not_looping(self):
        lc = LoopController(_make_fs())

        assert lc.check_loop(1000) is None

    def test_check_loop_returns_none_when_before_out(self):
        lc = LoopController(_make_fs())
        lc.on_space_down(2500)
        lc.on_space_up(3500)

        assert lc.check_loop(3000) is None

    def test_check_loop_returns_in_when_past_out(self):
        lc = LoopController(_make_fs())
        lc.on_space_down(2500)
        lc.on_space_up(3500)

        result = lc.check_loop(4001)

        assert result == 2000

    def test_space_up_in_normal_is_noop(self):
        lc = LoopController(_make_fs())

        lc.on_space_up(1000)

        assert lc.state == LoopState.NORMAL
