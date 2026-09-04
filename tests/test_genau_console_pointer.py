"""The pointer over the console Genau draws on top of its clip.

It was three closures in run_listener, threaded into the lifecycle as four
separate callbacks, and nothing in the suite reached any of them: the order the
chip and the panel are tried in, and the two-step a volume press takes, had no
test at all.
"""
from __future__ import annotations

from genau.console_pointer import ConsolePointer
from genau.pygame_view import VolumePress


class FakeView:
    """The four things the pointer asks a view."""

    def __init__(self, *, volume=None, pressed="", dragged=""):
        self._volume = volume
        self._pressed = pressed
        self._dragged = dragged
        self.shown: list[tuple[int, bool]] = []
        self.released = 0
        self.hovered: list[tuple[int, int]] = []
        self.asked: list[str] = []

    def volume_press_at(self, mx, my):
        self.asked.append("chip")
        return self._volume

    def console_press_at(self, mx, my) -> str:
        self.asked.append("panel")
        return self._pressed

    def console_drag_to(self, mx, my) -> str:
        return self._dragged

    def set_volume(self, level, muted) -> None:
        self.shown.append((level, muted))

    def console_release(self) -> None:
        self.released += 1

    def set_console_hover(self, mx, my) -> None:
        self.hovered.append((mx, my))


def _posted(tmp_path):
    return tmp_path / "dashboard_cmd.txt"


def _lines(path) -> list[str]:
    return path.read_text(encoding="utf-8").split() if path.exists() else []


class TestWhichThingAPressLandsOn:
    def test_the_chip_is_tried_before_the_panel(self, tmp_path):
        """It floats in its own corner, so a press on it is never also a press
        on the panel -- and asking the panel first would give a button under it
        the press instead."""
        view = FakeView(volume=VolumePress("audio_mute", 40, True), pressed="next")

        ConsolePointer(view, _posted(tmp_path)).press(3, 4)

        assert view.asked == ["chip"]
        assert _lines(_posted(tmp_path)) == ["audio_mute"]

    def test_a_press_off_the_chip_reaches_the_panel(self, tmp_path):
        view = FakeView(volume=None, pressed="next")

        ConsolePointer(view, _posted(tmp_path)).press(3, 4)

        assert view.asked == ["chip", "panel"]
        assert _lines(_posted(tmp_path)) == ["next"]

    def test_a_press_on_neither_asks_for_nothing(self, tmp_path):
        view = FakeView(volume=None, pressed="")

        ConsolePointer(view, _posted(tmp_path)).press(3, 4)

        assert _lines(_posted(tmp_path)) == []


class TestTheTwoStepsAVolumePressTakes:
    def test_the_chip_is_moved_and_the_level_asked_for(self, tmp_path):
        view = FakeView(volume=VolumePress("audio_set_volume|70", 70, False))

        ConsolePointer(view, _posted(tmp_path)).press(3, 4)

        assert view.shown == [(70, False)]
        assert _lines(_posted(tmp_path)) == ["audio_set_volume|70"]

    def test_the_chip_moves_before_fun_time_answers(self, tmp_path):
        """Shown first, asked for second: the chip is following the pointer and
        Fun Time's answer is a tick away."""
        view = FakeView(volume=VolumePress("audio_mute", 40, True))

        ConsolePointer(view, _posted(tmp_path)).press(3, 4)

        assert view.shown == [(40, True)]


class TestDraggingAndLettingGo:
    def test_a_drag_posts_what_the_bar_under_it_became(self, tmp_path):
        view = FakeView(dragged="set_speed|60")

        ConsolePointer(view, _posted(tmp_path)).drag(7, 9)

        assert _lines(_posted(tmp_path)) == ["set_speed|60"]

    def test_a_drag_whose_level_has_not_moved_says_nothing(self, tmp_path):
        view = FakeView(dragged="")

        ConsolePointer(view, _posted(tmp_path)).drag(7, 9)

        assert _lines(_posted(tmp_path)) == []

    def test_letting_go_reaches_the_view(self, tmp_path):
        view = FakeView()

        ConsolePointer(view, _posted(tmp_path)).release()

        assert view.released == 1

    def test_the_cursor_moving_tells_the_view_where_it_is(self, tmp_path):
        view = FakeView()

        ConsolePointer(view, _posted(tmp_path)).motion(11, 13)

        assert view.hovered == [(11, 13)]
