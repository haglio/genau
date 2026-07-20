"""Nau's mode HUD: what it says about the state the player is in."""
from __future__ import annotations

import numpy as np
from player_core.hud_panel import TEXT_MUTED, WHITE, load_font, text_width

from nau.console import ConsoleModel
from nau.hud import (
    DOT,
    ModeHud,
    NauHud,
    NauHudPainter,
    compilation_label,
    hud_xy,
)
from nau.hud import _PAD as PAD
from nau.library import FULL, MIXED, SHORTS


class TestLine:
    def test_says_which_length_mode_the_library_is_in(self):
        assert ModeHud(length_mode=MIXED).line == "Mixed"
        assert ModeHud(length_mode=FULL).line == "Full length"
        assert ModeHud(length_mode=SHORTS).line == "Shorts"

    def test_claims_no_length_mode_without_a_library_behind_the_playlist(self):
        """Fun Time can hand Nau a playlist and no library dirs; there is then no
        length filter running, so the HUD must not name one."""
        assert ModeHud(length_mode="").line == ""

    def test_names_the_compilation_holding_the_playlist_and_where_you_are_in_it(self):
        """The reported hole: inside a compilation nothing on screen said which one
        or how far through, so there was no way to tell you were held at all."""
        hud = ModeHud(length_mode=SHORTS, compilation="Vol6", position=9, total=20)

        assert hud.line == "Vol6 · 9/20"

    def test_a_compilation_does_not_repeat_the_length_mode(self):
        """The volume and the place in it are the whole answer; the length filter
        behind them is not what you are inside, and saying it too is noise."""
        for mode in (MIXED, SHORTS, FULL):
            hud = ModeHud(length_mode=mode, compilation="Vol6", position=9, total=20)

            assert hud.line == "Vol6 · 9/20"

    def test_says_when_fun_time_has_narrowed_the_playlist_to_f_mode(self):
        """F-mode keeps only the scripted videos.  Nau cannot see that in the
        playlist it is handed — a list of scripted videos looks like any other —
        so unless Fun Time says so, a library cut to a fraction of itself is
        indistinguishable from the whole thing."""
        assert ModeHud(length_mode=MIXED, f_mode=True).line == "Mixed · F-Mode"

    def test_f_mode_is_orthogonal_to_everything_else_the_line_says(self):
        """It is a filter over whatever is selecting the playlist, not one of the
        answers to it — so it rides alongside a compilation as readily as a length,
        and stands alone when neither is running."""
        inside = ModeHud(compilation="Vol6", position=9, total=20, f_mode=True)

        assert inside.line == "Vol6 · 9/20 · F-Mode"
        assert ModeHud(f_mode=True).line == "F-Mode"


class TestCompilationLabel:
    """Compilations are titled for a shelf, not for the corner of a video."""

    def test_keeps_only_the_volume(self):
        assert compilation_label(
            "various - Ultimate Example Studio Alpha Collection - Volume 6 (v1)"
        ) == "Volume 6"

    def test_an_undashed_title_survives_whole(self):
        assert compilation_label("redacted Overload 3") == "redacted Overload 3"


class TestPainter:
    def test_the_panel_is_wide_enough_for_what_it_says(self):
        """Sized to its contents, so a long volume title is never clipped and a
        bare "Shorts" does not sit in a mostly-empty slab."""
        long_hud = ModeHud(compilation="Angels of Debauchery 8", position=9, total=20)

        short = NauHudPainter().bgra(NauHud(modes=ModeHud(length_mode=SHORTS)))
        long = NauHudPainter().bgra(NauHud(modes=long_hud))

        assert long.shape[1] > short.shape[1]
        assert long.shape[1] > text_width(load_font(11), long_hud.line)

    def test_the_panel_is_there_even_with_no_words_for_it(self):
        """The dot has to be readable at all times — an absent dot cannot be told
        from an idle one — so the slab stays even when there is no mode to name.
        The controls are the player's own and are there regardless too."""
        bare = NauHudPainter().bgra(NauHud())
        titled = NauHudPainter().bgra(NauHud(modes=ModeHud(length_mode=FULL)))

        assert bare.size > 0
        assert bare.shape[0] == titled.shape[0]  # the dot's line is kept either way

    def test_the_dot_lights_up_only_while_the_primary_has_the_floor(self):
        """It says whether a bare "next" or "end loop" would land here rather than
        on a satellite.  White for yes, the palette's grey for no."""
        def dot(active: bool) -> tuple[int, ...]:
            bgra = NauHudPainter().bgra(NauHud(modes=ModeHud(length_mode=MIXED, active=active)))
            patch = bgra[PAD + 2:PAD + DOT, PAD:PAD + DOT - 2, :3]
            return tuple(int(v) for v in patch.reshape(-1, 3).mean(axis=0))[::-1]  # BGR -> RGB

        assert np.allclose(dot(True), WHITE, atol=40)
        assert np.allclose(dot(False), TEXT_MUTED, atol=40)

    def test_the_dot_does_not_shift_the_words_around(self):
        """The dot is always in the same place and always the same size, so the
        line beside it cannot jump when the floor moves to another player."""
        painter = NauHudPainter()

        lit = painter.bgra(NauHud(modes=ModeHud(length_mode=MIXED, active=True)))
        idle = NauHudPainter().bgra(NauHud(modes=ModeHud(length_mode=MIXED, active=False)))

        assert lit.shape == idle.shape

    def test_an_unchanged_hud_is_not_repainted(self):
        """It is asked for every frame at 60 fps; Pillow is far too slow to run
        that often, and what it draws changes a few times a minute at most."""
        painter = NauHudPainter()
        hud = NauHud(modes=ModeHud(length_mode=FULL))

        assert painter.bgra(hud) is painter.bgra(NauHud(modes=ModeHud(length_mode=FULL)))

    def test_a_changed_hud_is_repainted(self):
        painter = NauHudPainter()

        first = painter.bgra(NauHud(modes=ModeHud(length_mode=FULL)))
        second = painter.bgra(NauHud(modes=ModeHud(length_mode=SHORTS)))

        assert not np.array_equal(first, second)

    def test_hybrid_grows_the_panel_for_the_drive_controls(self):
        """The controls that steer the device only mean something while one is
        being steered, so the panel carries them — and grows — only then."""
        painter = NauHudPainter()

        plain = painter.bgra(NauHud(console=ConsoleModel(mode="nau"))).shape[0]
        hybrid = NauHudPainter().bgra(NauHud(console=ConsoleModel(mode="hybrid"))).shape[0]

        assert hybrid > plain

    def test_the_buttons_it_drew_are_the_buttons_it_reports(self):
        """Hit-testing runs off the last painting, so a press can only ever land
        on something that was actually drawn."""
        painter = NauHudPainter()

        painter.bgra(NauHud(console=ConsoleModel(mode="nau")))

        assert [b.action for _rect, b in painter.buttons if b.action][:2] == [
            "primary_prev", "primary_next"]


class TestPresses:
    """Which control a mouse press at a *window* point landed on.

    The panel's hit targets are placed from its own top-left corner, but presses
    arrive in the window's coordinates, so every hit test has to undo `hud_xy`
    first.  The painter is the only thing that knows both where the panel went
    and what it drew there, so it is the only thing that should have to.
    """

    @staticmethod
    def _painted(mode: str = "nau") -> NauHudPainter:
        painter = NauHudPainter()
        painter.bgra(NauHud(console=ConsoleModel(mode=mode)))
        return painter

    @staticmethod
    def _over(painter: NauHudPainter, action: str) -> tuple[int, int]:
        """The window point at the middle of the button posting *action*."""
        (bx, by, bw, bh), _button = next(
            (rect, b) for rect, b in painter.buttons if b.action == action)
        left, top = hud_xy()
        return left + bx + bw // 2, top + by + bh // 2

    def test_a_press_on_a_button_carries_that_buttons_command(self):
        painter = self._painted()

        assert painter.command_at(*self._over(painter, "primary_next")) == "primary_next"

    def test_a_press_on_the_video_below_the_panel_carries_nothing(self):
        """A press that misses every button falls through to the video, where it
        seeks or pauses — so "no button here" has to be sayable."""
        painter = self._painted()

        assert painter.command_at(900, 700) == ""

    def test_the_panels_own_corner_is_not_read_as_the_windows(self):
        """The panel is inset from the window corner.  Feeding a hit test the
        window point untranslated shifts every target up and left by that inset,
        which is how a press lands on the button beside the one under the cursor."""
        painter = self._painted()
        (bx, by, _bw, _bh), _button = next(
            (rect, b) for rect, b in painter.buttons if b.action == "primary_prev")

        assert painter.command_at(bx, by) == ""

    def test_the_cursor_over_a_button_is_reported_where_the_panel_can_draw_it(self):
        """The tooltip is drawn inside the panel, so the spot handed back has to be
        in the panel's coordinates, not the window's."""
        painter = self._painted()
        mx, my = self._over(painter, "primary_next")
        left, top = hud_xy()

        assert painter.hover_at(mx, my) == (mx - left, my - top)

    def test_the_cursor_over_no_button_is_not_reported_at_all(self):
        painter = self._painted()

        assert painter.hover_at(900, 700) is None


class TestPlacement:
    def test_the_panel_sits_in_the_top_left_corner(self):
        """Where the satellites put theirs, so every player in the family answers
        "what am I inside?" from the same place — in every mode now, since Genau
        no longer draws a panel of its own for this one to dodge."""
        assert hud_xy() == (8, 8)
