"""The primary console: the controls whichever player holds the slot draws."""
from __future__ import annotations

from pathlib import Path

from nau.console import (
    BUTTON,
    ConsoleModel,
    console_rows,
    genau_drives,
    hit_test,
    nau_displays,
    osr2_row,
    place_rows,
    read_console,
    shape_label,
    tooltip_at,
)


def _actions(model: ConsoleModel) -> list[str]:
    return [b.action for row in console_rows(model) for b in row if b.action]


def _button(model: ConsoleModel, action: str):
    return next(b for row in console_rows(model) for b in row if b.action == action)


def _osr2_button(model: ConsoleModel, action: str):
    return next(b for b in osr2_row(model) if b.action == action)


class TestShapeLabel:
    """The control that cycles the waveform names it on hover, so the name lives
    with the console rather than with the readout that no longer prints it."""

    def test_names_the_waveform_instead_of_leaving_it_to_the_curve(self):
        assert shape_label("sine") == "Sine"
        assert shape_label("rounded_square") == "Square"
        assert shape_label("sawtooth") == "Sawtooth"

    def test_an_unknown_shape_is_titled_rather_than_dropped(self):
        assert shape_label("half_moon") == "Half Moon"


class TestOsr2Row:
    """The device's own control: the broker that talks to the OSR2 at all."""

    def test_the_broker_is_a_control_and_says_which_way_a_press_goes(self):
        running = _osr2_button(ConsoleModel(broker=True), "broker_panel")
        down = _osr2_button(ConsoleModel(broker=False), "broker_panel")

        assert running.lit is True and "stop" in running.tooltip
        assert down.warn is True and "start" in down.tooltip

    def test_the_broker_is_the_only_control_on_that_line(self):
        """The takeover switch shared it until its one trigger — the OSR2's own
        free mode — turned out to be unreachable from here."""
        assert [b.action for b in osr2_row(ConsoleModel())] == ["broker_panel"]


class TestTransport:
    """Prev/next step Nau's video where Nau is on screen, Genau's clips where it
    is — with the actions that only make sense for each."""

    def test_nau_and_hybrid_step_the_video_and_act_on_it(self):
        for mode in ("nau", "hybrid"):
            actions = _actions(ConsoleModel(mode=mode))
            for action in ("primary_prev", "primary_next", "primary_nudge_prev",
                           "primary_nudge_next", "browse_library", "clipper_save",
                           "nau_record_tap"):
                assert action in actions, (mode, action)

    def test_record_is_there_in_hybrid_too_not_only_nau(self):
        """Nau is on screen in hybrid, so there is a loop to record — it went
        missing when the console only offered it in nau mode."""
        assert "nau_record_tap" in _actions(ConsoleModel(mode="hybrid"))

    def test_genau_steps_its_own_clips_and_can_mark_one_weird(self):
        actions = _actions(ConsoleModel(mode="genau"))

        assert "genau_prev_clip" in actions
        assert "genau_next_clip" in actions
        assert "genau_weird_clip" in actions  # the mark-weird the readout lacked

    def test_genau_offers_no_video_only_actions(self):
        """Nudge, open, clip and record act on a video; Genau's clips are not one."""
        actions = _actions(ConsoleModel(mode="genau"))

        for action in ("primary_nudge_prev", "browse_library", "clipper_save",
                       "nau_record_tap"):
            assert action not in actions


class TestPlaybackSpeed:
    def test_the_video_rate_has_controls_where_nau_is_on_screen(self):
        for mode in ("nau", "hybrid"):
            actions = _actions(ConsoleModel(mode=mode))
            assert "nau_speed_down" in actions and "nau_speed_up" in actions

    def test_genau_has_no_video_rate(self):
        """Genau's clips play at the stroke's rate, so there is no video rate to
        set — that Speed is the stroke's, on the readout."""
        actions = _actions(ConsoleModel(mode="genau"))

        assert "nau_speed_down" not in actions

    def test_the_rate_is_shown_as_a_read_out_between_the_arrows(self):
        rows = console_rows(with_speed(ConsoleModel(mode="nau"), 1.5))
        readouts = [b.glyph for row in rows for b in row if not b.action]

        assert "1.5×" in readouts


class TestDriveControls:
    """The amplitude/centre/speed arrows moved onto the readout, so they are not
    console buttons any more; the hands-free switches still are."""

    def test_the_switch_row_is_there_while_genau_drives(self):
        for mode in ("hybrid", "genau"):
            actions = _actions(ConsoleModel(mode=mode))
            for action in ("genau_toggle_cruise", "genau_toggle_auto_advance",
                           "genau_toggle_clip_lock", "genau_cycle_shape", "quarter_button"):
                assert action in actions, (mode, action)

    def test_holding_a_clip_is_offered_only_inside_auto_advance(self):
        """The hold exists only within auto advance, so outside it the control is
        faded and answers no press rather than posting a command that does
        nothing."""
        off = _button(ConsoleModel(mode="genau"), "genau_toggle_clip_lock")
        armed = _button(ConsoleModel(mode="genau", auto_advance=True), "genau_toggle_clip_lock")

        assert off.dim is True
        assert armed.dim is False

    def test_auto_advance_wears_the_pace_it_is_set_to(self):
        """A bare arming jitters a default with no single number, so it stays plain."""
        assert _button(ConsoleModel(mode="genau", advance_interval=5),
                       "genau_toggle_auto_advance").glyph == "aa 5s"
        assert _button(ConsoleModel(mode="genau"),
                       "genau_toggle_auto_advance").glyph == "aa"

    def test_the_axis_arrows_are_not_console_buttons(self):
        """They belong to the readout now, drawn on the bars themselves."""
        actions = _actions(ConsoleModel(mode="hybrid"))

        for action in ("genau_amplitude_up", "genau_center_down", "genau_speed_up"):
            assert action not in actions

    def test_nau_mode_has_none_of_the_drive_switches(self):
        actions = _actions(ConsoleModel(mode="nau"))

        assert not any(a.startswith("genau_") and a != "genau_activate" for a in actions)


class TestState:
    def test_the_mode_you_are_in_is_lit_and_the_others_are_not(self):
        model = ConsoleModel(mode="hybrid")

        assert _button(model, "hybrid_activate").lit is True
        assert _button(model, "nau_activate").lit is False

    def test_a_held_clip_holds_auto_advance_apart_from_merely_armed(self):
        armed = _button(ConsoleModel(mode="genau", auto_advance=True), "genau_toggle_auto_advance")
        held = _button(ConsoleModel(mode="genau", auto_advance=True, clip_locked=True),
                       "genau_toggle_auto_advance")

        assert armed.lit is True and armed.hold is False
        assert held.hold is True and held.lit is False


class TestModePredicates:
    def test_nau_displays_covers_nau_and_hybrid(self):
        assert nau_displays("nau") and nau_displays("hybrid")
        assert not nau_displays("genau")

    def test_genau_drives_covers_genau_and_hybrid(self):
        assert genau_drives("genau") and genau_drives("hybrid")
        assert not genau_drives("nau")


class TestReadConsole:
    def test_it_reads_back_what_fun_time_published(self, tmp_path: Path):
        import json
        path = tmp_path / "nau_console.json"
        path.write_text(json.dumps({
            "mode": "hybrid", "active": True, "osr2": "genau", "broker": True,
            "cruise": True, "auto_advance": True,
            "clip_locked": True, "shape": "sawtooth",
        }), encoding="utf-8")

        model = read_console(path)

        assert model.mode == "hybrid"
        assert model.active is True
        assert model.osr2 == "genau"
        assert model.broker is True
        assert (model.cruise, model.auto_advance, model.clip_locked) == (True, True, True)
        assert model.shape == "sawtooth"

    def test_a_torn_or_missing_file_keeps_the_console_you_have(self, tmp_path: Path):
        path = tmp_path / "nau_console.json"
        assert read_console(path) is None

        path.write_text('{"mode": "nau"', encoding="utf-8")
        assert read_console(path) is None


class TestLayout:
    def test_the_mode_row_leads_so_it_holds_its_place_across_modes(self):
        for mode in ("nau", "hybrid", "genau"):
            first = console_rows(ConsoleModel(mode=mode))[0]
            assert [b.action for b in first] == [
                "nau_activate", "hybrid_activate", "genau_activate"]

    def test_a_press_finds_the_button_under_it(self):
        placed = place_rows(console_rows(ConsoleModel(mode="nau")), x=0, y=0)
        rect, _b = next((r, b) for r, b in placed if b.action == "primary_next")

        assert hit_test(placed, rect[0] + 1, rect[1] + 1) == "primary_next"
        assert tooltip_at(placed, rect[0] + 1, rect[1] + 1) == "Next video"

    def test_a_press_off_every_button_posts_nothing(self):
        placed = place_rows(console_rows(ConsoleModel(mode="nau")), x=0, y=0)

        assert hit_test(placed, 5000, 5000) == ""

    def test_a_read_out_is_not_a_hit_target(self):
        placed = place_rows(console_rows(with_speed(ConsoleModel(mode="nau"), 1.0)), x=0, y=0)
        rect = next(r for r, b in placed if not b.action and b.glyph.endswith("×"))

        assert hit_test(placed, rect[0] + 1, rect[1] + 1) == ""

    def test_the_buttons_are_the_declared_size(self):
        placed = place_rows(console_rows(ConsoleModel(mode="nau")), x=0, y=0)

        assert all(rect[3] == BUTTON for rect, _b in placed)


def with_speed(model: ConsoleModel, speed: float) -> ConsoleModel:
    from dataclasses import replace
    return replace(model, playback_speed=speed)
