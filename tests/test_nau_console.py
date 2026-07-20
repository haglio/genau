"""Nau's console: the controls Fun Time's dashboard used to hold for the primary."""
from __future__ import annotations

from nau.console import (
    BUTTON,
    ConsoleModel,
    console_rows,
    hit_test,
    place_rows,
)


def _actions(model: ConsoleModel) -> list[str]:
    return [button.action for row in console_rows(model) for button in row]


class TestRows:
    def test_nau_mode_carries_the_players_own_controls_and_the_mode_switch(self):
        actions = _actions(ConsoleModel(mode="nau"))

        assert actions == [
            "primary_prev", "primary_next",
            "primary_nudge_prev", "primary_nudge_next",
            "open_file_dialog", "clipper_save", "nau_record_tap",
            "nau_activate", "hybrid_activate", "genau_activate",
        ]

    def test_nau_mode_leaves_out_the_drive_controls(self):
        """Nothing is driving the device from a waveform in Nau mode, so amplitude,
        centre, cruise and the rest would be buttons that do nothing visible."""
        actions = _actions(ConsoleModel(mode="nau"))

        assert not any(action.startswith("genau_") and action != "genau_activate"
                       for action in actions)

    def test_hybrid_adds_the_drive_controls_because_genau_is_driving(self):
        actions = _actions(ConsoleModel(mode="hybrid"))

        for action in ("genau_amplitude_up", "genau_center_down", "genau_speed_up",
                       "genau_toggle_cruise", "genau_cycle_shape", "quarter_button",
                       "genau_toggle_auto"):
            assert action in actions

    def test_record_belongs_to_nau_alone(self):
        """Recording a loop is Nau's own; in Hybrid the primary slot is shared with
        a waveform and there is no loop to mark."""
        assert "nau_record_tap" in _actions(ConsoleModel(mode="nau"))
        assert "nau_record_tap" not in _actions(ConsoleModel(mode="hybrid"))

    def test_the_mode_you_are_in_is_lit_and_the_others_are_not(self):
        rows = console_rows(ConsoleModel(mode="hybrid"))
        modes = {b.action: b for row in rows for b in row if b.action.endswith("_activate")}

        assert modes["hybrid_activate"].lit is True
        assert modes["nau_activate"].lit is False
        assert modes["genau_activate"].lit is False

    def test_a_suppressed_takeover_is_marked_rather_than_merely_unlit(self):
        """Allowed and suppressed are both live states — an unlit button would
        read as "off", which is not the same as "Genau may not take the device"."""
        def takeover(allowed: bool):
            rows = console_rows(ConsoleModel(mode="hybrid", takeover_allowed=allowed))
            return next(b for row in rows for b in row if b.action == "genau_toggle_auto")

        assert takeover(True).lit is True
        assert takeover(False).warn is True

    def test_each_drive_pair_is_labelled_with_what_it_moves(self):
        """Three identical up/down pairs in a row say nothing about which is
        amplitude and which is speed — the dashboard labelled them and so must
        this.  A label is placed like a control but posts nothing."""
        rows = console_rows(ConsoleModel(mode="hybrid"))
        drive = next(row for row in rows if any(b.action == "genau_amplitude_up" for b in row))

        assert [b.glyph for b in drive if not b.action] == ["Amp", "Ctr", "Spd"]

        placed = place_rows(rows, x=0, y=0)
        label_rect = next(r for r, b in placed if b.glyph == "Amp" and not b.action)
        centre = (label_rect[0] + label_rect[2] // 2, label_rect[1] + label_rect[3] // 2)
        assert hit_test(placed, *centre) == ""

    def test_cruise_lights_while_it_is_holding_the_speed(self):
        rows = console_rows(ConsoleModel(mode="hybrid", cruise=True))
        cruise = next(b for row in rows for b in row if b.action == "genau_toggle_cruise")

        assert cruise.lit is True

    def test_a_control_at_its_limit_is_dimmed_and_stops_being_clickable(self):
        """The dashboard greyed these out at the ends of their range; a HUD button
        that still looks live but does nothing is worse than one that says so."""
        model = ConsoleModel(mode="hybrid", limits=frozenset({"amp_max", "spd_min"}))
        rows = console_rows(model)
        by_action = {b.action: b for row in rows for b in row}

        assert by_action["genau_amplitude_up"].dim is True
        assert by_action["genau_amplitude_down"].dim is False
        assert by_action["genau_speed_down"].dim is True

        placed = place_rows(rows, x=0, y=0)
        assert hit_test(placed, *_centre(placed, "genau_amplitude_up")) == ""
        assert hit_test(placed, *_centre(placed, "genau_amplitude_down")) == "genau_amplitude_down"


def _centre(placed, action: str) -> tuple[int, int]:
    rect = next(r for r, button in placed if button.action == action)
    return rect[0] + rect[2] // 2, rect[1] + rect[3] // 2


class TestLayout:
    def test_rows_stack_and_buttons_run_along_them(self):
        rows = console_rows(ConsoleModel(mode="nau"))

        placed = place_rows(rows, x=10, y=20)

        first = [rect for rect, _b in placed][0]
        assert first[0] == 10 and first[1] == 20
        assert all(rect[3] == BUTTON for rect, _b in placed)
        # Every button lands somewhere different.
        assert len({rect[:2] for rect, _b in placed}) == len(placed)

    def test_a_press_off_every_button_posts_nothing(self):
        placed = place_rows(console_rows(ConsoleModel(mode="nau")), x=0, y=0)

        assert hit_test(placed, 5000, 5000) == ""
