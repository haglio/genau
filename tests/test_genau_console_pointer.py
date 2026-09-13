"""The pointer over the console Genau draws on top of its clip.

It was three closures in run_listener, threaded into the lifecycle as four
separate callbacks, and nothing in the suite reached any of them: the order the
chip and the panel are tried in, and the two-step a volume press takes, had no
test at all.
"""
from __future__ import annotations

from player_core.timeline import TIMELINE_HEIGHT

from genau.console_pointer import OMNIPAUSE_TOGGLE, ConsolePointer
from genau.volume_chip import VolumePress


class FakeChip:
    def __init__(self, asked: list[str], press=None):
        self._asked = asked
        self._press = press
        self.shown: list[tuple[int, bool]] = []

    def press_at(self, mx, my, *, win_w, win_h):
        self._asked.append("chip")
        return self._press

    def show(self, level, muted) -> None:
        self.shown.append((level, muted))


class FakePanel:
    def __init__(self, asked: list[str], pressed="", dragged="", *, covering=False):
        self._asked = asked
        self._pressed = pressed
        self._dragged = dragged
        self._covering = covering
        self.released = 0
        self.hovered: list[tuple[int, int]] = []

    def press_at(self, mx, my) -> str:
        self._asked.append("panel")
        return self._pressed

    def covers(self, mx, my) -> bool:
        return self._covering

    def drag_to(self, mx, my) -> str:
        return self._dragged

    def release(self) -> None:
        self.released += 1

    def hover_at(self, mx, my) -> None:
        self.hovered.append((mx, my))


class FakeWindow:
    size = (800, 600)

    def __init__(self, *, hud_active: bool = False):
        self.hud_active = hud_active


class FakeScrubber:
    """The clip's bar: across the window's lower edge while a clip is up."""

    def __init__(self, asked, *, showing=True):
        self._asked = asked
        self._showing = showing

    def takes(self, my, *, win_h):
        return self._showing and my >= win_h - TIMELINE_HEIGHT

    @staticmethod
    def fraction_at(mx, *, win_w):
        return mx / win_w


def _pointer(tmp_path, *, volume=None, pressed="", dragged="", clip=True,
             hud_active=False, covering=False):
    """The pointer over a fake chip, panel and bar, plus the order it asked them in."""
    asked: list[str] = []
    chip = FakeChip(asked, volume)
    panel = FakePanel(asked, pressed, dragged, covering=covering)
    scrubber = FakeScrubber(asked, showing=clip)
    seeks: list[float] = []
    pointer = ConsolePointer(panel, chip, scrubber,
                             window=FakeWindow(hud_active=hud_active),
                             dashboard_cmd_file=_posted(tmp_path), seek=seeks.append)
    pointer.seeks = seeks
    return pointer, chip, panel, asked


def _posted(tmp_path):
    return tmp_path / "dashboard_cmd.txt"


def _lines(path) -> list[str]:
    return path.read_text(encoding="utf-8").split() if path.exists() else []


class TestWhichThingAPressLandsOn:
    def test_the_chip_is_tried_before_the_panel(self, tmp_path):
        """It floats in its own corner, so a press on it is never also a press
        on the panel -- and asking the panel first would give a button under it
        the press instead."""
        pointer, _chip, _panel, asked = _pointer(
            tmp_path, volume=VolumePress("audio_mute", 40, True), pressed="next")

        pointer.press(3, 4)

        assert asked == ["chip"]
        assert _lines(_posted(tmp_path)) == ["audio_mute"]

    def test_a_press_off_the_chip_reaches_the_panel(self, tmp_path):
        pointer, _chip, _panel, asked = _pointer(tmp_path, pressed="next")

        pointer.press(3, 4)

        assert asked == ["chip", "panel"]
        assert _lines(_posted(tmp_path)) == ["next"]

    def test_a_press_on_neither_is_a_press_on_the_clip(self, tmp_path):
        """Genau's clip is the main player here, and it has no pause of its own
        to give -- the room's flag file owns its playback -- so a press that no
        control took asks Fun Time to freeze the whole room."""
        pointer, _chip, _panel, _asked = _pointer(tmp_path)

        pointer.press(3, 4)

        assert _lines(_posted(tmp_path)) == [OMNIPAUSE_TOGGLE]

    def test_a_press_on_the_panel_between_its_buttons_is_not_the_clip(self, tmp_path):
        pointer, _chip, _panel, _asked = _pointer(tmp_path, covering=True)

        pointer.press(3, 4)

        assert _lines(_posted(tmp_path)) == []

    def test_in_hud_mode_there_is_no_clip_under_the_press(self, tmp_path):
        """This window is the see-through layer over Nau then: the picture's own
        presses reach Nau through the color key and never arrive here, so what
        does arrive landed on the HUD's opaque chrome and means nothing more."""
        pointer, _chip, _panel, _asked = _pointer(tmp_path, hud_active=True)

        pointer.press(3, 4)

        assert _lines(_posted(tmp_path)) == []

    def test_a_button_the_panel_took_is_never_also_the_clip(self, tmp_path):
        pointer, _chip, _panel, _asked = _pointer(tmp_path, pressed="main_next")

        pointer.press(3, 4)

        assert _lines(_posted(tmp_path)) == ["main_next"]


class TestTheTwoStepsAVolumePressTakes:
    def test_the_chip_is_moved_and_the_level_asked_for(self, tmp_path):
        pointer, chip, _panel, _asked = _pointer(
            tmp_path, volume=VolumePress("audio_set_volume|70", 70, False))

        pointer.press(3, 4)

        assert chip.shown == [(70, False)]
        assert _lines(_posted(tmp_path)) == ["audio_set_volume|70"]

    def test_the_chip_moves_before_fun_time_answers(self, tmp_path):
        """Shown first, asked for second: the chip is following the pointer and
        Fun Time's answer is a tick away."""
        pointer, chip, _panel, _asked = _pointer(
            tmp_path, volume=VolumePress("audio_mute", 40, True))

        pointer.press(3, 4)

        assert chip.shown == [(40, True)]


class TestDraggingAndLettingGo:
    def test_a_drag_posts_what_the_bar_under_it_became(self, tmp_path):
        pointer, _chip, _panel, _asked = _pointer(tmp_path, dragged="set_speed|60")

        pointer.drag(7, 9)

        assert _lines(_posted(tmp_path)) == ["set_speed|60"]

    def test_a_drag_whose_level_has_not_moved_says_nothing(self, tmp_path):
        pointer, _chip, _panel, _asked = _pointer(tmp_path, dragged="")

        pointer.drag(7, 9)

        assert _lines(_posted(tmp_path)) == []

    def test_letting_go_reaches_the_panel(self, tmp_path):
        pointer, _chip, panel, _asked = _pointer(tmp_path)

        pointer.release()

        assert panel.released == 1

    def test_the_cursor_moving_tells_the_panel_where_it_is(self, tmp_path):
        pointer, _chip, panel, _asked = _pointer(tmp_path)

        pointer.motion(11, 13)

        assert panel.hovered == [(11, 13)]


class TestAPressOnTheClipsOwnBar:
    """The clip's bar seeks, and goes on seeking while the pointer is held.  The
    frame is a picture of where the device is, so the seek moves the device --
    which is why it goes to the engine rather than out as a console command."""

    def test_a_press_along_the_lower_edge_seeks(self, tmp_path):
        pointer, _chip, _panel, asked = _pointer(tmp_path)

        pointer.press(400, 595)

        assert pointer.seeks == [0.5]
        assert asked == ["chip"]  # the chip is still tried first, and missed

    def test_a_drag_after_it_goes_on_seeking_and_letting_go_stops(self, tmp_path):
        pointer, _chip, _panel, _asked = _pointer(tmp_path, dragged="speed_up")

        pointer.press(400, 595)
        pointer.drag(600, 595)
        pointer.release()
        pointer.drag(200, 595)

        assert pointer.seeks == [0.5, 0.75]
        # Let go, and the lower edge is the panel's business again.
        assert _posted(tmp_path).read_text(encoding="utf-8").split() == ["speed_up"]

    def test_with_no_clip_up_the_lower_edge_is_the_panels_again(self, tmp_path):
        pointer, _chip, _panel, _asked = _pointer(tmp_path, clip=False, pressed="main_lock")

        pointer.press(400, 595)

        assert pointer.seeks == []
        assert _posted(tmp_path).read_text(encoding="utf-8").split() == ["main_lock"]
