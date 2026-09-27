"""The volume chip Genau draws in genau mode, where its window is the primary
display.

Fun Time owns the level, so a press is a request — but its answer is a tick
away, and a slider that waited for it would trail the pointer by a frame.  So
the press says both what to ask for and what to show meanwhile, and the caller
does both; asking is not itself a move.

Where the chip is drawn and which part of it a press landed on belong to the
row that carries it at the foot of the console
(:mod:`genau.console_pointer`); what is here is what it shows and what it asks.
"""
from __future__ import annotations

from player_core.volume import VolumeHud

from genau.volume_chip import VolumeChip


def _chip(level: int = 30, muted: bool = False) -> VolumeChip:
    chip = VolumeChip()
    chip.show(level, muted)
    return chip


def test_the_published_level_is_the_one_it_is_holding():
    """Genau neither owns the level nor plays the sound — a companion process
    carries the clip music — so what it draws is whatever Fun Time last said."""
    chip = VolumeChip()

    chip.show(45, True)

    assert chip.shown == VolumeHud(volume=45, muted=True)


def test_the_slider_asks_for_the_level_it_was_pressed_at():
    press = VolumeChip.pressed_the_slider(100)

    assert press.command == "audio_set_volume|100"
    assert (press.level, press.muted) == (100, False)


def test_the_speaker_asks_for_the_mute():
    press = _chip().pressed_the_speaker()

    assert press.command == "audio_mute"
    assert press.muted is True


def test_pressing_a_muted_speaker_asks_to_unmute():
    press = _chip(muted=True).pressed_the_speaker()

    assert press.command == "audio_unmute"
    assert press.muted is False


def test_the_mute_leaves_the_level_where_it_was():
    """Muting is not turning it down: unmuting has to come back to here."""
    assert _chip(level=30).pressed_the_speaker().level == 30


def test_asking_does_not_itself_move_the_chip():
    """It used to, which is why nothing could ask what a press would do without
    it having already happened.  Asking twice must give the same answer."""
    chip = _chip(level=30)

    chip.pressed_the_slider(100)

    assert chip.pressed_the_speaker().level == 30, "the level is still the published one"
    assert chip.pressed_the_speaker().muted is True, "and it is still unmuted"
