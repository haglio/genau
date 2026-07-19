"""Nau's mode HUD: what it says about the state the player is in."""
from __future__ import annotations

import numpy as np
from player_core.hud_panel import GREEN, load_font, text_width

from nau.hud import ModeHud, ModeHudPainter, compilation_label, hud_xy
from nau.library import FULL, SHORTS
from nau.overlay import indicator_xy


class TestLines:
    def test_says_which_length_mode_the_library_is_in(self):
        assert ModeHud(length_mode=FULL).lines == ("Full length",)
        assert ModeHud(length_mode=SHORTS).lines == ("Shorts",)

    def test_claims_no_length_mode_without_a_library_behind_the_playlist(self):
        """Fun Time can hand Nau a playlist and no library dirs; there is then no
        length filter running, so the HUD must not name one."""
        assert ModeHud(length_mode="").lines == ()

    def test_names_the_compilation_holding_the_playlist_and_where_you_are_in_it(self):
        """The reported hole: inside a compilation nothing on screen said which one
        or how far through, so there was no way to tell you were held at all."""
        hud = ModeHud(length_mode=SHORTS, compilation="Vol6", position=9, total=20)

        assert hud.lines == ("Shorts", "Vol6 · 9/20")


class TestCompilationLabel:
    """Compilations are titled for a shelf, not for the corner of a video."""

    def test_keeps_only_the_volume(self):
        assert compilation_label(
            "various - Ultimate Example Studio Alpha Collection - Volume 6 (v1)"
        ) == "Volume 6"

    def test_an_undashed_title_survives_whole(self):
        assert compilation_label("redacted Overload 3") == "redacted Overload 3"


class TestPainter:
    def test_the_panel_is_wide_enough_for_the_longest_line(self):
        """Sized to what it says, so a long volume title is never clipped and a
        bare "Shorts" does not sit in a mostly-empty slab."""
        long_line = ModeHud(length_mode=SHORTS, compilation="Angels of Debauchery 8",
                            position=9, total=20)

        short = ModeHudPainter().bgra(ModeHud(length_mode=SHORTS))
        long = ModeHudPainter().bgra(long_line)

        widest = max(text_width(load_font(11), line) for line in long_line.lines)
        assert long.shape[1] > short.shape[1]
        assert long.shape[1] > widest
        assert long.shape[0] > short.shape[0]  # two lines are taller than one

    def test_nothing_to_say_paints_nothing(self):
        """No library behind the playlist and no compilation: the corner stays
        clear rather than carrying an empty slab."""
        assert ModeHudPainter().bgra(ModeHud()) is None

    def test_the_dot_goes_green_only_while_a_compilation_holds_the_playlist(self):
        """The dot is the glance-level answer to "am I held?" — the same idiom the
        satellites' lock band uses."""
        def green_pixels(hud: ModeHud) -> int:
            bgra = ModeHudPainter().bgra(hud)
            rgb = bgra[:, :, [2, 1, 0]]
            return int((rgb == np.array(GREEN, dtype=np.uint8)).all(axis=2).sum())

        assert green_pixels(ModeHud(length_mode=SHORTS)) == 0
        assert green_pixels(
            ModeHud(length_mode=SHORTS, compilation="Vol6", position=9, total=20)
        ) > 0

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
    def test_the_panel_hangs_below_the_state_indicator(self):
        """Right-aligned with it and clear of it, so the two read as one corner and
        neither lands on the video's middle."""
        panel_w = 140
        ix, iy = indicator_xy(1200)

        x, y = hud_xy(1200, panel_w)

        assert x + panel_w == ix + 26  # flush right with the indicator
        assert y > iy
