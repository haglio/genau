"""The primary console painter: the top line, the controls, and the readout."""
from __future__ import annotations

import numpy as np
from player_core.hud_panel import TEXT_MUTED, WHITE, load_font, text_width

from genau.drive_hud import DriveHud
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


def _drive() -> DriveHud:
    return DriveHud(speed=50, amplitude=80, center=50, shape="sine",
                    waveform=tuple(0.5 + 0.4 * np.sin(i / 6) for i in range(80)))


class TestLine:
    def test_says_which_length_mode_the_library_is_in(self):
        assert ModeHud(length_mode=MIXED).line == "Mixed"
        assert ModeHud(length_mode=FULL).line == "Full length"
        assert ModeHud(length_mode=SHORTS).line == "Shorts"

    def test_claims_no_length_mode_without_a_library_behind_the_playlist(self):
        assert ModeHud(length_mode="").line == ""

    def test_names_the_compilation_and_where_you_are_in_it(self):
        hud = ModeHud(length_mode=SHORTS, compilation="Vol6", position=9, total=20)

        assert hud.line == "Vol6 · 9/20"

    def test_says_when_fun_time_has_narrowed_to_f_mode(self):
        assert ModeHud(length_mode=MIXED, f_mode=True).line == "Mixed · F-Mode"
        assert ModeHud(f_mode=True).line == "F-Mode"


class TestCompilationLabel:
    def test_keeps_only_the_volume(self):
        assert compilation_label(
            "various - Ultimate Example Studio Alpha Collection - Volume 6 (v1)"
        ) == "Volume 6"

    def test_an_undashed_title_survives_whole(self):
        assert compilation_label("Scene Five 3") == "Scene Five 3"


class TestPainter:
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
        """A pink "B" on blue while the service is up and red while it is down —
        the broker acts on the room's own service rather than on a player, so it
        does not take the on/off colors the controls beside it use."""
        for broker, fill in ((True, (48, 128, 224)), (False, (255, 60, 60))):
            painter = ConsolePainter()
            rgb = _rgb(painter.bgra(
                ConsoleHud(console=ConsoleModel(mode="nau", broker=broker))))
            (bx, by, bw, bh), _b = next(
                (rect, b) for rect, b in painter.buttons if b.action == "broker_panel")
            box = rgb[by:by + bh, bx:bx + bw]

            assert tuple(box[bh // 2, 2]) == fill
            assert (box == np.array((200, 80, 160), dtype=box.dtype)).all(axis=2).any()


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

        assert painter.command_at(*self._over(painter, "primary_next")) == "primary_next"

    def test_a_press_that_missed_every_button_carries_nothing(self):
        assert self._painted().command_at(2000, 2000) == ""

    def test_the_panels_own_corner_is_not_read_as_the_windows(self):
        painter = self._painted()
        (bx, by, _bw, _bh), _b = next(
            (rect, b) for rect, b in painter.buttons if b.action == "primary_prev")

        assert painter.command_at(bx, by) == ""

    def test_a_readouts_arrow_press_reaches_genau(self):
        painter = ConsolePainter()
        painter.bgra(ConsoleHud(
            console=ConsoleModel(mode="hybrid", osr2="genau"), drive=_drive()))

        assert painter.command_at(*self._over(painter, "genau_amplitude_up")) == "genau_amplitude_up"

    def test_the_readouts_controls_are_dead_while_a_funscript_has_the_device(self):
        """Genau is paused through a funscript's stretch, so a stroke it is not
        sending cannot be adjusted — pressing one woke Genau onto a device the
        funscript was already driving, and the two fought over it."""
        painter = ConsolePainter()
        painter.bgra(ConsoleHud(
            console=ConsoleModel(mode="hybrid", osr2="funscript"), drive=_drive()))

        over = self._over(painter, "genau_amplitude_up")
        assert painter.command_at(*over) == ""
        assert all(b.dim for _rect, b in painter.buttons if b.action.startswith("genau_amplitude"))

    def test_the_cursor_over_a_button_is_reported_in_panel_coordinates(self):
        painter = self._painted()
        mx, my = self._over(painter, "primary_next")
        left, top = hud_xy()

        assert painter.hover_at(mx, my) == (mx - left, my - top)


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
