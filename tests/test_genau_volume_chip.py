"""The volume chip Genau draws in genau mode, where its window is the primary
display.

Fun Time owns the level, so a press is a request — but its answer is a tick
away, and a slider that waited for it would trail the pointer by a frame.  So
the press says both what to ask for and what to show meanwhile, and the caller
does both; asking is not itself a move.
"""
from __future__ import annotations

from player_core.timeline import TIMELINE_HEIGHT
from player_core.volume import CHIP_W, chip_xy

from genau.volume_chip import VolumeChip

WIN_W, WIN_H = 800, 600


def _chip(level: int = 30, muted: bool = False) -> VolumeChip:
    chip = VolumeChip()
    chip.show(level, muted)
    return chip


def _at(part: str) -> tuple[int, int]:
    vx, vy = chip_xy(win_w=WIN_W, win_h=WIN_H, timeline_h=0)
    return (vx + CHIP_W - 2, vy + 10) if part == "far end" else (vx + 3, vy + 10)


def _press(chip: VolumeChip, part: str):
    return chip.press_at(*_at(part), win_w=WIN_W, win_h=WIN_H)


def test_it_sits_where_naus_does_with_no_timeline_under_it():
    """Genau's window IS the primary display in genau mode, so reaching for the
    sound must not mean finding the control somewhere else than in Nau's modes.
    Measured against the row Nau draws it in rather than against Genau's own
    call, which is what a chip nine pixels above Nau's still passed."""
    assert VolumeChip.corner(win_w=WIN_W, win_h=WIN_H) == chip_xy(
        win_w=WIN_W, win_h=WIN_H, timeline_h=TIMELINE_HEIGHT)


def test_the_published_level_is_the_one_it_is_holding():
    """Genau neither owns the level nor plays the sound — a companion process
    carries the clip music — so what it draws is whatever Fun Time last said.

    Read back through a press rather than through an accessor of its own: a
    press on the speaker carries the level it would unmute to, which is the
    only place the held level is observable from outside."""
    chip = VolumeChip()

    chip.show(45, True)

    press = _press(chip, "speaker")
    assert (press.command, press.level, press.muted) == ("audio_unmute", 45, False)


def test_the_far_end_of_the_track_asks_for_full_volume():
    press = _press(_chip(), "far end")

    assert press.command == "audio_set_volume|100"
    assert (press.level, press.muted) == (100, False)


def test_the_speaker_end_asks_for_the_mute():
    press = _press(_chip(), "speaker")

    assert press.command == "audio_mute"
    assert press.muted is True


def test_pressing_a_muted_speaker_asks_to_unmute():
    press = _press(_chip(muted=True), "speaker")

    assert press.command == "audio_unmute"
    assert press.muted is False


def test_the_mute_leaves_the_level_where_it_was():
    """Muting is not turning it down: unmuting has to come back to here."""
    assert _press(_chip(level=30), "speaker").level == 30


def test_asking_does_not_itself_move_the_chip():
    """It used to, which is why nothing could ask what a press would do without
    it having already happened.  Asking twice must give the same answer."""
    chip = _chip(level=30)

    _press(chip, "far end")

    assert _press(chip, "speaker").level == 30, "the level is still the published one"
    assert _press(chip, "speaker").muted is True, "and it is still unmuted"


def test_a_press_nowhere_near_it_asks_for_nothing():
    """So the console under the chip gets it instead."""
    assert _chip().press_at(10, 10, win_w=WIN_W, win_h=WIN_H) is None
