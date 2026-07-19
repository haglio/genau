from __future__ import annotations

import pygame

from nau.library_source import PHASE_DISCOVER, PHASE_DURATIONS
from nau.loading import (
    REPAINT_INTERVAL_S,
    progress_fraction,
    progress_text,
    quit_requested,
    repaint_due,
)


class TestQuitRequested:
    """A wait long enough to need a loading screen is long enough that closing
    the window has to work during it."""

    def test_closing_the_window_quits(self):
        assert quit_requested([pygame.event.Event(pygame.QUIT)])

    def test_ctrl_q_quits_as_it_does_in_playback(self):
        event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_q, mod=pygame.KMOD_CTRL)
        assert quit_requested([event])

    def test_an_ordinary_keypress_does_not(self):
        event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_q, mod=0)
        assert not quit_requested([event])


class TestRepaintDue:
    """A warm cache reports all 525 entries in a fraction of a second; painting
    every one of them would cost more than the work being reported."""

    def test_holds_off_within_the_interval(self):
        assert not repaint_due(
            phase="durations", last_phase="durations", now=10.0, last_paint_s=10.0,
        )

    def test_paints_once_the_interval_has_passed(self):
        assert repaint_due(
            phase="durations", last_phase="durations",
            now=10.0 + REPAINT_INTERVAL_S, last_paint_s=10.0,
        )

    def test_a_new_phase_always_paints(self):
        assert repaint_due(
            phase="durations", last_phase="discover", now=10.0, last_paint_s=10.0,
        )


class TestProgressText:
    def test_counting_phase_shows_how_far(self):
        assert progress_text(PHASE_DURATIONS, 128, 525) == "Reading video lengths... 128 of 525"

    def test_uncounted_phase_is_just_the_message(self):
        assert progress_text(PHASE_DISCOVER, 0, 0) == "Finding videos..."


class TestProgressFraction:
    def test_no_total_is_indeterminate(self):
        assert progress_fraction(0, 0) is None

    def test_counts_the_work_behind_it(self):
        assert progress_fraction(1, 4) == 0.25
