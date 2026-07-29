"""The primary console painter: the top line, the controls, and the readout."""
from __future__ import annotations

import numpy as np
from player_core.hud_panel import ICON_GRIDS, TEXT_MUTED, WHITE, load_font, text_width

from genau.drive_hud import AMPLITUDE, CENTER, SPEED, DriveHud
from nau.console import ConsoleModel
from nau.hud import (
    ConsoleHud,
    ConsolePainter,
    ModeHud,
    compilation_label,
    hud_xy,
    with_playback_speed,
)
from nau.hud import _PAD as PAD
from nau.library import FULL, MIXED, SHORTS


def _drive(**over) -> DriveHud:
    return DriveHud(speed=50, amplitude=80, center=50, shape="sine",
                    waveform=tuple(0.5 + 0.4 * np.sin(i / 6) for i in range(80)),
                    **over)


def _line(*, locked: bool = True, **modes) -> str:
    """The status line for a primary in *modes* whose lock is *locked*."""
    return ConsoleHud(modes=ModeHud(**modes),
                      console=ConsoleModel(locked=locked)).status_line


class TestLine:
    def test_says_whether_the_primary_is_holding_the_video_on_screen(self):
        """Each satellite leads its line with this word, and the primary has the
        same lock — one padlock, for whichever player holds the slot."""
        assert _line(locked=True) == "Locked"
        assert _line(locked=False) == "Unlocked"

    def test_says_which_length_mode_the_library_is_in_and_says_it_last(self):
        """The length mode is what the satellites' act filter is — a narrowing of
        what may play — so it takes the same place, at the end of the line.

        "Mixed" is every length there is, so it narrows nothing and prints nothing,
        exactly as a satellite prints nothing where its filter would go when it has
        none.  It also no longer says enough to be worth the room: the library has
        grown a third kind of thing, and one word for "some of each" cannot say
        which.
        """
        assert _line(length_mode=MIXED) == "Locked"
        assert _line(length_mode=FULL) == "Locked · Full length"
        assert _line(length_mode=SHORTS) == "Locked · Shorts"

    def test_claims_no_length_mode_without_a_library_behind_the_playlist(self):
        """A playlist Fun Time drives has no length filter of its own to report, so
        that slot stays empty.  The lock is still said: it belongs to the primary
        slot whatever is feeding it."""
        assert _line(length_mode="") == "Locked"

    def test_a_genau_primary_says_its_lock_and_the_pace_it_moves_at(self):
        """Genau has no library, no compilation and no filters.  What it has is the
        same lock every player has and, while that lock is off, the seconds it
        leaves each clip up — which is its browse order, so it sits where the
        satellites put theirs, straight after the lock.  Held, there is no pace to
        report: the clip stays until something moves it."""
        def line(**over) -> str:
            return ConsoleHud(console=ConsoleModel(mode="genau", **over),
                              drive=_drive(advance_interval=5)).status_line

        assert line(locked=False) == "Unlocked · 5s"
        assert line(locked=True) == "Locked"

    def test_the_pace_belongs_to_genau_and_is_not_claimed_while_nau_is_showing(self):
        """Hybrid draws the readout, so the pace is there to read — but Nau is on
        screen and an unlocked Nau plays through its playlist rather than moving on
        a timer, so saying seconds would describe the wrong player."""
        assert ConsoleHud(console=ConsoleModel(mode="hybrid", locked=False),
                          drive=_drive(advance_interval=5)).status_line == "Unlocked"

    def test_names_the_compilation_and_where_you_are_in_it(self):
        """A compilation is the primary's loop — a fixed set it plays through
        rather than the browse it came from — so it leads the line the way a
        satellite's loop does, and displaces "Unlocked" there for the same reason:
        a loop is repeat-all, and nothing is being held.  "Locked" still joins it,
        being a hold at one place inside the set.  The length mode stays on behind
        it, since ending the compilation drops you back into it."""
        def line(**over) -> str:
            return _line(compilation="Vol6", position=9, total=20, **over)

        assert line(locked=False) == "Vol6 · 9/20"
        assert line(locked=True) == "Vol6 · 9/20 · Locked"
        assert line(locked=False, length_mode=SHORTS) == "Vol6 · 9/20 · Shorts"

    def test_says_when_fun_time_has_narrowed_to_f_mode(self):
        """Between the lock and the length, where each satellite puts it: F-mode
        cuts the whole library to the funscripted videos and the length mode then
        narrows what is left, so the coarser filter is named first."""
        assert _line(f_mode=True) == "Locked · F-Mode"
        assert _line(length_mode=SHORTS, f_mode=True) == "Locked · F-Mode · Shorts"


class TestCompilationLabel:
    def test_keeps_only_the_volume(self):
        assert compilation_label(
            "various - Ultimate Example Studio Alpha Collection - Volume 6 (v1)"
        ) == "Volume 6"

    def test_an_undashed_title_survives_whole(self):
        assert compilation_label("Scene Five 3") == "Scene Five 3"


class TestPainter:
    def test_a_tooltip_longer_than_the_panel_is_wide_stays_on_the_panel(self):
        """The lock button's tooltip wants 354px of box on a 238px console, so it
        used to be drawn straight off the right edge and lose its tail.  Fitting it
        is player_core's job — this guards that the console hands it the panel's own
        bounds, since passing anything wider puts the box back over the edge."""
        painter = ConsolePainter()
        hud = ConsoleHud(console=ConsoleModel(mode="nau", locked=False))
        plain = _rgb(painter.bgra(hud))  # also lays the buttons out, so one can be hovered
        tiny = load_font(8)
        (x, y, w, h), _button = max(
            ((rect, button) for rect, button in painter.buttons if button.tooltip),
            key=lambda pair: text_width(tiny, pair[1].tooltip))
        tipped = _rgb(ConsolePainter().bgra(hud, hover=(x + w // 2, y + h // 2)))

        def edge_ink(rgb) -> int:
            return int((rgb[:, -2:] > 200).all(axis=2).sum())

        assert not np.array_equal(plain, tipped)  # it drew something
        assert edge_ink(tipped) == edge_ink(plain) == 0

    def test_the_top_line_sits_tight_to_the_top(self):
        """The old console left a tall empty band above its first line; the status
        line now heads the console within a body line-height of the slab's top, the
        way each satellite's does."""
        painter = ConsolePainter()
        bgra = painter.bgra(ConsoleHud(modes=ModeHud(length_mode=FULL)))
        rgb = _rgb(bgra)

        # There is ink (the status text) within the first line-height below the pad.
        line_h = sum(load_font(11).getmetrics())
        band = rgb[PAD:PAD + line_h, :, :]
        assert (band > 200).any()

    def test_the_status_leads_and_the_file_name_is_the_muted_line_under_it(self):
        """The satellites lead with what they are showing, not with a file name, so
        the primary does too: the length mode or compilation in the body face, the
        file beneath it in the muted one."""
        painter = ConsolePainter()
        bgra = painter.bgra(ConsoleHud(modes=ModeHud(
            video="Some Video Name", length_mode=MIXED)))
        rgb = _rgb(bgra)

        body_h = sum(load_font(11).getmetrics())
        bright_rows = np.nonzero((rgb > 200).any(axis=(1, 2)))[0]
        muted = (rgb[:, :, 0] > 100) & (rgb[:, :, 0] < 160)
        muted_rows = np.nonzero(muted.any(axis=1))[0]

        assert bright_rows.min() < PAD + body_h          # the status is on top …
        assert muted_rows.max() > bright_rows.min()      # … the file name below it

    def test_a_longer_file_name_widens_the_panel(self):
        """It is drawn, not truncated, so the slab grows to hold it."""
        narrow = ConsolePainter().bgra(ConsoleHud(modes=ModeHud(video="Short")))
        wide = ConsolePainter().bgra(
            ConsoleHud(modes=ModeHud(video="A Much Much Longer Video Name Indeed")))

        assert wide.shape[1] > narrow.shape[1]

    def test_hybrid_grows_the_panel_for_the_readout(self):
        painter = ConsolePainter()
        plain = painter.bgra(ConsoleHud(console=ConsoleModel(mode="nau"))).shape[0]
        driving = ConsolePainter().bgra(
            ConsoleHud(console=ConsoleModel(mode="hybrid"), drive=_drive())).shape[0]

        assert driving > plain

    def test_the_dot_lights_only_while_the_primary_has_the_floor(self):
        def dot(active: bool):
            bgra = ConsolePainter().bgra(
                ConsoleHud(console=ConsoleModel(mode="nau", active=active)))
            body = sum(load_font(11).getmetrics())
            cx, cy = PAD + 5, PAD + body // 2  # the dot's own centre
            return tuple(int(v) for v in _rgb(bgra)[cy, cx])

        assert np.allclose(dot(True), WHITE, atol=45)
        assert np.allclose(dot(False), TEXT_MUTED, atol=45)

    def test_the_dot_does_not_shift_the_words_around(self):
        """The dot is always in the same place and the same size — active only
        recolours it — so the line beside it cannot jump when the floor moves to
        another player."""
        painter = ConsolePainter()

        lit = painter.bgra(ConsoleHud(console=ConsoleModel(mode="nau", active=True)))
        idle = ConsolePainter().bgra(ConsoleHud(console=ConsoleModel(mode="nau", active=False)))

        assert lit.shape == idle.shape

    def test_an_unchanged_hud_is_not_repainted(self):
        painter = ConsolePainter()
        hud = ConsoleHud(console=ConsoleModel(mode="nau"))

        assert painter.bgra(hud) is painter.bgra(ConsoleHud(console=ConsoleModel(mode="nau")))

    def test_the_readouts_arrows_are_hit_targets_even_though_it_draws_them(self):
        """The readout paints its own amplitude/centre/speed arrows; the console
        adds them to its hit targets so a press on the trace's controls posts what
        is drawn there."""
        painter = ConsolePainter()
        painter.bgra(ConsoleHud(console=ConsoleModel(mode="hybrid"), drive=_drive()))

        actions = {b.action for _rect, b in painter.buttons}
        for action in ("genau_amplitude_up", "genau_center_down", "genau_speed_up"):
            assert action in actions

    def test_the_osr2_state_is_shown(self):
        """A boxed word, lower in the HUD — a read-out of what has the device, not
        a line jammed in with the mode."""
        painter = ConsolePainter()
        bgra = painter.bgra(ConsoleHud(
            console=ConsoleModel(mode="nau", osr2="funscript", broker=True)))
        rgb = _rgb(bgra)
        # FunScript is drawn green; there is green ink somewhere below the top line.
        green = (rgb[:, :, 1] > 130) & (rgb[:, :, 0] < 110) & (rgb[:, :, 2] < 110)
        assert green.any()

    def test_a_control_that_is_on_fills_white_rather_than_green(self):
        """Green means the favorites and the funscripts everywhere in this
        family — the OSR2 pill says FunScript in it, and that is the only thing on
        the console entitled to it.  The mode you are in is not one of them."""
        painter = ConsolePainter()
        rgb = _rgb(painter.bgra(ConsoleHud(console=ConsoleModel(mode="hybrid"))))
        (bx, by, bw, bh), _b = next(
            (rect, b) for rect, b in painter.buttons if b.action == "hybrid_activate")
        box = rgb[by:by + bh, bx:bx + bw].astype(int)

        shades, counts = np.unique(box.reshape(-1, 3), axis=0, return_counts=True)
        assert tuple(shades[counts.argmax()]) == (255, 255, 255)
        green = (box[:, :, 1] > 130) & (box[:, :, 0] < 110) & (box[:, :, 2] < 110)
        assert not green.any()

    def test_the_broker_wears_the_face_it_had_on_the_dashboard(self):
        """Its own pink mark on blue while the service is up and red while it is
        down — the broker acts on the room's own service rather than on a player,
        so it does not take the on/off colors the controls beside it use."""
        for broker, fill in ((True, (48, 128, 224)), (False, (255, 60, 60))):
            box = self._broker_box(broker)

            assert tuple(box[box.shape[0] // 2, 2]) == fill
            assert (box == np.array((200, 80, 160), dtype=box.dtype)).all(axis=2).any()

    def test_a_control_that_stands_for_an_app_wears_that_apps_mark(self):
        """`broker_icon.ico` and `fmode_icon.ico` are five-by-five letters, and one
        set in the body face is a thin thing beside them.  What has to hold is the
        shape: the grid the .ico carries, in its pink, whatever the button is
        doing underneath it."""
        for action, grid in (("broker_panel", ICON_GRIDS["B"]),
                             ("primary_fmode", ICON_GRIDS["F"])):
            box = self._button_box(action, ConsoleModel(
                mode="nau", broker=True, f_mode=True))
            pink = (box == np.array((200, 80, 160), dtype=box.dtype)).all(axis=2)
            ys, xs = np.nonzero(pink)
            cell = (xs.max() - xs.min() + 1) / 5
            drawn = [
                "".join("#" if pink[int(ys.min() + (r + 0.5) * cell),
                                    int(xs.min() + (c + 0.5) * cell)] else "."
                        for c in range(5))
                for r in range(5)
            ]

            assert drawn == list(grid), action

    @staticmethod
    def _button_box(action: str, model: ConsoleModel) -> np.ndarray:
        painter = ConsolePainter()
        rgb = _rgb(painter.bgra(ConsoleHud(console=model)))
        (bx, by, bw, bh), _b = next(
            (rect, b) for rect, b in painter.buttons if b.action == action)
        return rgb[by:by + bh, bx:bx + bw]

    def _broker_box(self, broker: bool) -> np.ndarray:
        return self._button_box("broker_panel", ConsoleModel(mode="nau", broker=broker))

    def test_f_mode_is_the_one_lit_control_that_stays_green(self):
        """It narrows the playlist to the videos that have a funscript, and green
        is what the funscripts and the favorites own."""
        box = self._button_box("primary_fmode",
                               ConsoleModel(mode="nau", f_mode=True)).astype(int)

        shades, counts = np.unique(box.reshape(-1, 3), axis=0, return_counts=True)
        assert tuple(shades[counts.argmax()]) == (48, 160, 48)

    def test_a_lit_marks_ink_stays_white_over_a_colored_fill(self):
        """The Dash's mic keeps its white glyph while the panel under it goes
        blue.  A record button whose circle went dark while it recorded read as a
        different button rather than as the same one recording."""
        painter = ConsolePainter()
        rgb = _rgb(painter.bgra(
            ConsoleHud(console=ConsoleModel(mode="nau", record="recording"))))
        (bx, by, bw, bh), _b = next(
            (rect, b) for rect, b in painter.buttons if b.action == "nau_record_tap")
        box = rgb[by:by + bh, bx:bx + bw].astype(int)

        assert tuple(box[bh // 2, 2]) == (255, 60, 60)   # the fill went red …
        assert (box > 240).all(axis=2).any()             # … and the circle did not


class TestPresses:
    @staticmethod
    def _painted(mode: str = "nau") -> ConsolePainter:
        painter = ConsolePainter()
        painter.bgra(ConsoleHud(console=ConsoleModel(mode=mode)))
        return painter

    @staticmethod
    def _over(painter: ConsolePainter, action: str) -> tuple[int, int]:
        (bx, by, bw, bh), _b = next(
            (rect, b) for rect, b in painter.buttons if b.action == action)
        left, top = hud_xy()
        return left + bx + bw // 2, top + by + bh // 2

    def test_a_press_on_a_button_carries_that_buttons_command(self):
        painter = self._painted()

        assert painter.press_at(*self._over(painter, "primary_next")) == "primary_next"

    def test_a_press_that_missed_every_button_carries_nothing(self):
        assert self._painted().press_at(2000, 2000) == ""

    def test_the_panels_own_corner_is_not_read_as_the_windows(self):
        painter = self._painted()
        (bx, by, _bw, _bh), _b = next(
            (rect, b) for rect, b in painter.buttons if b.action == "primary_prev")

        assert painter.press_at(bx, by) == ""

    def test_a_readouts_arrow_press_reaches_genau(self):
        painter = ConsolePainter()
        painter.bgra(ConsoleHud(
            console=ConsoleModel(mode="hybrid", osr2="genau"), drive=_drive()))

        assert painter.press_at(*self._over(painter, "genau_amplitude_up")) == "genau_amplitude_up"

    def test_the_readouts_controls_are_dead_while_a_funscript_has_the_device(self):
        """Genau is paused through a funscript's stretch, so a stroke it is not
        sending cannot be adjusted — pressing one woke Genau onto a device the
        funscript was already driving, and the two fought over it."""
        painter = ConsolePainter()
        painter.bgra(ConsoleHud(
            console=ConsoleModel(mode="hybrid", osr2="funscript"), drive=_drive()))

        over = self._over(painter, "genau_amplitude_up")
        assert painter.press_at(*over) == ""
        assert all(b.dim for _rect, b in painter.buttons if b.action.startswith("genau_amplitude"))

    def test_the_cursor_over_a_button_is_reported_in_panel_coordinates(self):
        painter = self._painted()
        mx, my = self._over(painter, "primary_next")
        left, top = hud_xy()

        assert painter.hover_at(mx, my) == (mx - left, my - top)


class TestDrags:
    """The readout's bars are set by pressing in them and dragging along them, so
    a level is reached in one gesture rather than by walking a mark to it."""

    @staticmethod
    def _painted(osr2: str = "genau") -> ConsolePainter:
        painter = ConsolePainter()
        painter.bgra(ConsoleHud(
            console=ConsoleModel(mode="hybrid", osr2=osr2), drive=_drive()))
        return painter

    @staticmethod
    def _band(painter: ConsolePainter, axis: str):
        return next(track for track in painter.tracks if track.axis == axis)

    @staticmethod
    def _at(track, along: float) -> tuple[int, int]:
        """A window point that fraction of the way up (or along) *track*.

        Only speed runs left to right; the trace and the amplitude bar are both
        read as heights, the trace despite being the wider of the two.
        """
        x, y, w, h = track.rect
        left, top = hud_xy()
        if track.axis == SPEED:
            return left + x + round(along * (w - 1)), top + y + h // 2
        return left + x + w // 2, top + y + round((1 - along) * (h - 1))

    def test_a_press_along_the_speed_bar_sets_the_speed(self):
        painter = self._painted()

        point = self._at(self._band(painter, SPEED), 1.0)
        assert painter.press_at(*point) == "genau_speed_100"

    def test_a_press_in_the_trace_moves_the_stroke_s_center(self):
        painter = self._painted()

        point = self._at(self._band(painter, CENTER), 1.0)
        assert painter.press_at(*point) == "genau_center_100"

    def test_a_press_up_the_amplitude_bar_sets_how_far_the_stroke_reaches(self):
        painter = self._painted()

        point = self._at(self._band(painter, AMPLITUDE), 1.0)
        assert painter.press_at(*point) == "genau_amp_100"

    def test_the_bar_a_press_took_hold_of_keeps_the_drag(self):
        """A press latches its bar, so a drag that wanders off it — past its end,
        or out over another one — goes on setting the level it started on."""
        painter = self._painted()
        speed = self._band(painter, SPEED)
        painter.press_at(*self._at(speed, 1.0))

        assert painter.holding is True
        left, _top = hud_xy()
        assert painter.drag_to(left + speed.rect[0] - 500, 0) == "genau_speed_0"
        assert painter.drag_to(*self._at(speed, 1.0)) == "genau_speed_100"

    def test_a_drag_says_nothing_while_the_level_under_it_has_not_moved(self):
        """Every mouse motion fires, and each one that repeats the level is a line
        in the command file for Fun Time to route to where Genau already is."""
        painter = self._painted()
        speed = self._band(painter, SPEED)
        painter.press_at(*self._at(speed, 1.0))

        assert painter.drag_to(*self._at(speed, 1.0)) == ""

    def test_letting_go_ends_the_drag(self):
        painter = self._painted()
        painter.press_at(*self._at(self._band(painter, SPEED), 0.0))

        painter.release()

        assert painter.holding is False
        assert painter.drag_to(*self._at(self._band(painter, SPEED), 1.0)) == ""

    def test_a_press_on_a_button_leaves_no_bar_latched_behind_it(self):
        """Otherwise the bar a previous press held would keep taking the pointer
        long after the gesture that grabbed it was over."""
        painter = self._painted()
        painter.press_at(*self._at(self._band(painter, SPEED), 0.0))
        (bx, by, bw, bh), _b = next(
            (rect, b) for rect, b in painter.buttons if b.action == "primary_next")
        left, top = hud_xy()

        painter.press_at(left + bx + bw // 2, top + by + bh // 2)

        assert painter.holding is False

    def test_the_bars_are_dead_while_a_funscript_has_the_device(self):
        """The whole readout is dimmed through a funscript's stretch — a stroke
        Genau is not sending cannot be dragged any more than it can be stepped."""
        painter = self._painted(osr2="funscript")

        point = self._at(self._band(painter, SPEED), 1.0)
        assert painter.press_at(*point) == ""
        assert painter.holding is False

    def test_there_are_no_bars_at_all_where_nothing_is_driving(self):
        """In nau mode the readout is not drawn, so its bands must not linger as
        targets over whatever the console puts in that space instead."""
        painter = ConsolePainter()
        painter.bgra(ConsoleHud(console=ConsoleModel(mode="nau")))

        assert painter.tracks == []

    def test_each_bar_names_what_it_sets_on_hover(self):
        """Nothing else on a HUD drawn into the video says a bar can be dragged."""
        painter = self._painted()
        left, top = hud_xy()

        for axis in (SPEED, CENTER, AMPLITUDE):
            x, y, w, h = self._band(painter, axis).rect
            assert painter.hover_at(left + x + w // 2, top + y + h // 2) is not None


class TestPlaybackSpeed:
    def test_the_drawing_player_folds_in_its_own_rate(self):
        """Fun Time does not publish Nau's video rate — Nau knows it and adds it
        at draw time, so the console shows the rate the video is really playing."""
        console = with_playback_speed(ConsoleModel(mode="nau"), 1.75)

        assert console.playback_speed == 1.75


class TestPlacement:
    def test_the_panel_sits_in_the_top_left_corner(self):
        assert hud_xy() == (8, 8)


def _rgb(bgra: np.ndarray) -> np.ndarray:
    return bgra[:, :, [2, 1, 0]]
