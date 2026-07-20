"""Nau's mode HUD: what it says about the state the player is in."""
from __future__ import annotations

import numpy as np
from player_core.hud_panel import GREEN, TEXT_MUTED, load_font, text_width

from nau.hud import (
    DOT,
    GENAU_PANEL_W,
    PAD,
    ModeHud,
    ModeHudPainter,
    compilation_label,
    hud_xy,
)
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
    def test_the_panel_is_sized_to_what_it_says(self):
        """Sized to its line, so a long volume title is never clipped and a bare
        "Shorts" does not sit in a mostly-empty slab."""
        long_hud = ModeHud(compilation="Nights of Nonsense 8", position=9, total=20)

        short = ModeHudPainter().bgra(ModeHud(length_mode=SHORTS))
        long = ModeHudPainter().bgra(long_hud)

        assert long.shape[1] > short.shape[1]
        assert long.shape[1] > text_width(load_font(11), long_hud.line)
        assert long.shape[0] == short.shape[0]  # one line either way

    def test_the_panel_is_there_even_with_no_words_for_it(self):
        """The dot has to be readable at all times — an absent dot cannot be told
        from an idle one — so the slab stays even when there is no mode to name."""
        assert ModeHudPainter().bgra(ModeHud()) is not None

    def test_the_dot_lights_up_only_while_the_primary_has_the_floor(self):
        """It says whether a bare "next" or "end loop" would land here rather than
        on a satellite.  Green for yes, the palette's grey for no."""
        def dot(active: bool) -> tuple[int, ...]:
            bgra = ModeHudPainter().bgra(ModeHud(length_mode=MIXED, active=active))
            patch = bgra[PAD + 2:PAD + DOT, PAD:PAD + DOT - 2, :3]
            return tuple(int(v) for v in patch.reshape(-1, 3).mean(axis=0))[::-1]  # BGR -> RGB

        assert np.allclose(dot(True), GREEN, atol=40)
        assert np.allclose(dot(False), TEXT_MUTED, atol=40)

    def test_the_dot_does_not_shift_the_words_around(self):
        """The dot is always in the same place and always the same size, so the
        line beside it cannot jump when the floor moves to another player."""
        painter = ModeHudPainter()

        lit = painter.bgra(ModeHud(length_mode=MIXED, active=True))
        idle = ModeHudPainter().bgra(ModeHud(length_mode=MIXED, active=False))

        assert lit.shape == idle.shape

    def test_an_unchanged_hud_is_not_repainted(self):
        """It is asked for every frame at 60 fps; Pillow is far too slow to run
        that often, and the modes change a few times an hour."""
        painter = ModeHudPainter()
        hud = ModeHud(length_mode=FULL)

        assert painter.bgra(hud) is painter.bgra(ModeHud(length_mode=FULL))

    def test_a_changed_hud_is_repainted(self):
        painter = ModeHudPainter()

        first = painter.bgra(ModeHud(length_mode=FULL))
        second = painter.bgra(ModeHud(length_mode=SHORTS))

        assert not np.array_equal(first, second)


class TestPlacement:
    def test_the_panel_sits_in_the_top_left_corner(self):
        """Where the satellites put theirs, so every player in the family answers
        "what am I inside?" from the same place."""
        x, y = hud_xy(hybrid=False)

        assert (x, y) == (8, 8)

    def test_hybrid_shifts_it_clear_of_genau(self):
        """In Hybrid, Genau's window is a transparent layer over Nau's and its own
        panel holds that same corner, so Nau's starts past it instead of under it."""
        plain_x, plain_y = hud_xy(hybrid=False)

        x, y = hud_xy(hybrid=True)

        assert x >= plain_x + GENAU_PANEL_W
        assert y == plain_y
