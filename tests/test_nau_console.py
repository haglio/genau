"""The main console: the controls whichever player holds the slot draws."""
from __future__ import annotations

from pathlib import Path

from nau.console import (
    BROKER_ICON,
    BUTTON,
    GAP,
    GROUP_GAP,
    MINIMIZE_ICON,
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

    def test_the_broker_asks_for_its_own_icon_rather_than_the_word(self):
        """It is the room's own service, not one of the players' controls, and it
        had a mark of its own on the dashboard: the painter draws that rather than
        giving it the on/off colors everything else here takes."""
        broker = _osr2_button(ConsoleModel(), "broker_panel")

        assert broker.glyph == BROKER_ICON
        assert broker.width == BUTTON


class TestTransport:
    """Prev/next step Nau's video where Nau is on screen, Genau's clips where it
    is — with the actions that only make sense for each."""

    def test_nau_and_hybrid_step_the_video_and_act_on_it(self):
        for mode in ("nau", "hybrid"):
            actions = _actions(ConsoleModel(mode=mode))
            for action in ("main_prev", "main_next", "main_nudge_prev",
                           "main_nudge_next", "main_fmode", "browse_library",
                           "clipper_save", "nau_record_tap"):
                assert action in actions, (mode, action)

    def test_f_mode_is_the_main_players_own_and_lights_while_it_is_on(self):
        """Fun Time's dashboard carried one F-mode switch for the room; every
        player carries its own now, and this is the main player's — its playlist
        narrowed to the videos that have a funscript."""
        off = _button(ConsoleModel(mode="nau"), "main_fmode")
        on = _button(ConsoleModel(mode="nau", f_mode=True), "main_fmode")

        assert off.lit is False
        assert on.lit is True

    def test_f_mode_is_not_offered_where_there_is_no_nau_playlist(self):
        """In genau mode the main slot is Genau's, and the playlist F-mode
        narrows is not what is playing — the same reason nudge and record go."""
        assert "main_fmode" not in _actions(ConsoleModel(mode="genau"))

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

        for action in ("main_nudge_prev", "browse_library", "clipper_save",
                       "nau_record_tap", "main_fmode"):
            assert action not in actions


class TestLock:
    """The padlock: whether the video repeats or plays on into the playlist."""

    def test_the_video_can_be_held_wherever_nau_is_on_screen(self):
        for mode in ("nau", "hybrid"):
            assert "main_lock" in _actions(ConsoleModel(mode=mode))

    def test_it_is_lit_while_the_video_is_held(self):
        assert _button(ConsoleModel(mode="nau", locked=True), "main_lock").lit is True
        assert _button(ConsoleModel(mode="nau", locked=False), "main_lock").lit is False

    def test_it_says_which_way_a_press_goes(self):
        held = _button(ConsoleModel(mode="nau", locked=True), "main_lock")
        loose = _button(ConsoleModel(mode="nau", locked=False), "main_lock")

        assert held.tooltip.startswith("Locked") and "play on" in held.tooltip
        assert loose.tooltip.startswith("Unlocked") and "hold this video" in loose.tooltip

    def test_it_pairs_with_f_mode_and_stands_apart_from_everything_else(self):
        """The two switches are the states the player sits in — this video held,
        the playlist narrowed — where the four marks each move the video now and
        the browser opens a file.  So they sit together, and clear of both.  The
        lock also shares the transport's command prefix, which would otherwise
        have made it read as a fifth step."""
        placed = place_rows(console_rows(ConsoleModel(mode="nau")), x=0, y=0)
        by_action = {b.action: rect for rect, b in placed}
        step, lock = by_action["main_next"], by_action["main_lock"]
        fmode, browse = by_action["main_fmode"], by_action["browse_library"]

        assert lock[0] - (step[0] + step[2]) == GROUP_GAP
        assert fmode[0] - (lock[0] + lock[2]) == GAP        # the pair runs together
        assert browse[0] - (fmode[0] + fmode[2]) == GROUP_GAP


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


class TestClipSeconds:
    """How long an unlocked Genau leaves each clip up — the only thing left of
    what used to be the auto-advance switch."""

    def test_the_pace_has_arrows_where_genau_is_on_screen(self):
        actions = _actions(ConsoleModel(mode="genau"))
        assert "genau_advance_down" in actions and "genau_advance_up" in actions

    def test_nau_and_hybrid_show_the_video_rate_instead(self):
        """The row is about what the transport is stepping, and in those modes
        that is Nau's video, which has a playback rate rather than a pace."""
        for mode in ("nau", "hybrid"):
            actions = _actions(ConsoleModel(mode=mode))
            assert "genau_advance_down" not in actions
            assert "nau_speed_down" in actions

    def test_the_seconds_are_shown_as_a_read_out_between_the_arrows(self):
        rows = console_rows(ConsoleModel(mode="genau", advance_interval=7))
        readouts = [b.glyph for row in rows for b in row if not b.action]

        assert "7s" in readouts
        assert "Clip seconds" in readouts


class TestDriveControls:
    """The amplitude/centre/speed arrows moved onto the readout, so they are not
    console buttons any more; the hands-free switches still are."""

    def test_the_switch_row_is_there_while_genau_drives(self):
        for mode in ("hybrid", "genau"):
            actions = _actions(ConsoleModel(mode=mode))
            for action in ("genau_toggle_cruise", "genau_cycle_shape", "quarter_button"):
                assert action in actions, (mode, action)

    def test_auto_advance_is_no_longer_a_switch_of_its_own(self):
        """Arming it and holding a clip against it were two controls that could
        disagree, and the padlock beside them was a second lock on a console that
        already had Nau's.  What is left is the pace, on its own row."""
        actions = _actions(ConsoleModel(mode="genau"))

        assert "genau_toggle_auto_advance" not in actions
        assert "genau_toggle_clip_lock" not in actions

    def test_the_axis_arrows_are_not_console_buttons(self):
        """They belong to the readout now, drawn on the bars themselves."""
        actions = _actions(ConsoleModel(mode="hybrid"))

        for action in ("genau_amplitude_up", "genau_center_down", "genau_speed_up"):
            assert action not in actions

    def test_nau_mode_has_none_of_the_drive_switches(self):
        actions = _actions(ConsoleModel(mode="nau"))

        assert not any(a.startswith("genau_") and a != "genau_activate" for a in actions)


class TestLockAcrossModes:
    """One padlock on the console, whichever player is showing: it holds Nau's
    video in nau and hybrid, and Genau's clip in genau."""

    def test_every_mode_offers_exactly_one_padlock(self):
        for mode in ("nau", "hybrid", "genau"):
            actions = _actions(ConsoleModel(mode=mode))
            assert actions.count("main_lock") == 1, mode

    def test_it_is_lit_while_whatever_is_showing_is_held(self):
        for mode in ("nau", "hybrid", "genau"):
            assert _button(ConsoleModel(mode=mode, locked=True), "main_lock").lit is True
            assert _button(ConsoleModel(mode=mode, locked=False), "main_lock").lit is False

    def test_in_genau_it_says_what_the_clip_does_and_how_fast(self):
        held = _button(ConsoleModel(mode="genau", locked=True, advance_interval=7),
                       "main_lock")
        loose = _button(ConsoleModel(mode="genau", locked=False, advance_interval=7),
                        "main_lock")

        assert held.tooltip.startswith("Locked") and "every 7s" in held.tooltip
        assert loose.tooltip.startswith("Unlocked") and "every 7s" in loose.tooltip


class TestState:
    def test_the_mode_you_are_in_is_lit_and_the_others_are_not(self):
        model = ConsoleModel(mode="hybrid")

        assert _button(model, "hybrid_activate").lit is True
        assert _button(model, "nau_activate").lit is False

    def test_nothing_but_the_recording_and_its_loop_takes_a_color_of_its_own(self):
        """Every switch here lights in the same white; red and blue are left to the
        two halves of a recording, which is the one control that has to say which
        of two things it is doing."""
        model = ConsoleModel(mode="genau", cruise=True, locked=True)
        colored = [b.action for row in console_rows(model) for b in row
                   if b.warn or b.hold]

        assert colored == []

    def test_f_mode_keeps_the_green_the_other_switches_gave_up(self):
        """It narrows the playlist to what has a funscript, and green means the
        favorites and the funscripts — so it is the one lit control here that is
        not white."""
        assert _button(ConsoleModel(mode="nau", f_mode=True), "main_fmode").favorite is True
        assert _button(ConsoleModel(mode="genau"), "genau_toggle_cruise").favorite is False

    def test_the_record_button_tells_marking_from_looping(self):
        """One key does both halves, and they look identical otherwise: the mark
        is still open in one and the loop is running in the other.  Red while it
        is being recorded, blue once it repeats."""
        idle = _button(ConsoleModel(mode="nau"), "nau_record_tap")
        marking = _button(ConsoleModel(mode="nau", record="recording"), "nau_record_tap")
        looping = _button(ConsoleModel(mode="nau", record="looping"), "nau_record_tap")

        assert (idle.warn, idle.hold) == (False, False)
        assert (marking.warn, marking.hold) == (True, False)
        assert (looping.warn, looping.hold) == (False, True)

    def test_the_record_button_says_which_press_comes_next(self):
        for record, wanted in (("normal", "Record"), ("recording", "out point"),
                               ("looping", "drop the loop")):
            button = _button(ConsoleModel(mode="nau", record=record), "nau_record_tap")
            assert wanted in button.tooltip


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
            "mode": "hybrid", "active": True, "f_mode": True, "osr2": "genau",
            "broker": True, "record": "looping", "locked": False, "cruise": True,
            "shape": "sawtooth",
        }), encoding="utf-8")

        model = read_console(path)

        assert model.mode == "hybrid"
        assert model.active is True
        assert model.f_mode is True
        assert model.osr2 == "genau"
        assert model.broker is True
        assert model.record == "looping"
        assert model.locked is False
        assert model.cruise is True
        assert model.shape == "sawtooth"

    def test_a_panel_that_says_nothing_about_the_lock_reads_as_locked(self, tmp_path: Path):
        """Which is where both players open, and what a Fun Time too old to
        publish the flag is still describing."""
        import json
        path = tmp_path / "nau_console.json"
        path.write_text(json.dumps({"mode": "nau"}), encoding="utf-8")

        assert read_console(path).locked is True
        assert ConsoleModel().locked is True

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
                "nau_activate", "hybrid_activate", "genau_activate", "main_minimize"]

    def test_minimize_rides_the_row_that_never_changes(self):
        """It parks the slot's window whatever is on it, so it must be in the row
        that is the same in every mode — the transport moves and resizes as the
        mode flips, which would put this button somewhere else each time."""
        for mode in ("nau", "hybrid", "genau"):
            placed = place_rows(console_rows(ConsoleModel(mode=mode)), x=0, y=0)
            rect = next(r for r, b in placed if b.action == "main_minimize")
            assert rect == next(r for r, b in place_rows(
                console_rows(ConsoleModel(mode="nau")), x=0, y=0)
                if b.action == "main_minimize"), mode

    def test_minimize_stands_apart_from_the_modes_it_sits_beside(self):
        """It is about the window, not about which app owns the slot, so it must
        not read as a fourth mode: the wider group gap separates it."""
        placed = place_rows(console_rows(ConsoleModel(mode="nau")), x=0, y=0)
        by_action = {b.action: r for r, b in placed}
        genau, minimize = by_action["genau_activate"], by_action["main_minimize"]

        assert minimize[0] - (genau[0] + genau[2]) == GROUP_GAP

    def test_minimize_asks_for_a_drawn_bar_rather_than_a_font_glyph(self):
        """Windows' own minimize mark is in a face this HUD does not load, and
        Pillow draws tofu for what a face lacks — so the console names a marker and
        the painter draws it, the way the waveform does."""
        button = _button(ConsoleModel(mode="genau"), "main_minimize")

        assert button.glyph == MINIMIZE_ICON
        assert "taskbar" in button.tooltip

    def test_a_press_finds_the_button_under_it(self):
        placed = place_rows(console_rows(ConsoleModel(mode="nau")), x=0, y=0)
        rect, _b = next((r, b) for r, b in placed if b.action == "main_next")

        assert hit_test(placed, rect[0] + 1, rect[1] + 1) == "main_next"
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
