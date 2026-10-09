"""The pointer over the console Genau draws on top of its clip.

It was three closures in run_listener, threaded into the lifecycle as four
separate callbacks, and nothing in the suite reached any of them: the order the
chip and the panel are tried in, and the two-step a volume press takes, had no
test at all.
"""
from __future__ import annotations

import pytest
from player_core.loop_dial import DIAL_SIZE, dial_xy
from player_core.playhead import lower_edge_height
from player_core.timeline import TIMELINE_HEIGHT, bar_track_x
from player_core.volume import CHIP_H, CHIP_W, PAD, SPEAKER_W, chip_xy

from genau.console_pointer import OMNIPAUSE_TOGGLE, ConsolePointer
from genau.volume_chip import VolumePress

# Where the panel says it drew the clip's row, and how to aim at a point of it.
ROW_W = 340
ROW_H = lower_edge_height(ROW_W, timeline_h=TIMELINE_HEIGHT)
ROW_RECT = (12, 300, ROW_W, ROW_H)


def _on_the_row(px: int, py: int) -> tuple[int, int]:
    return ROW_RECT[0] + px, ROW_RECT[1] + py


_TRACK_X0, _TRACK_X1 = bar_track_x(ROW_W)
_ALONG = ROW_H - TIMELINE_HEIGHT // 2
TRACK_MIDDLE = _on_the_row((_TRACK_X0 + _TRACK_X1) // 2, _ALONG)
TRACK_START = _on_the_row(_TRACK_X0, _ALONG)
_CHIP_X, _CHIP_Y = chip_xy(win_w=ROW_W, win_h=ROW_H, timeline_h=TIMELINE_HEIGHT)
ON_THE_SLIDER = _on_the_row(_CHIP_X + (SPEAKER_W + CHIP_W - PAD) // 2,
                            _CHIP_Y + CHIP_H // 2)
ON_THE_SPEAKER = _on_the_row(_CHIP_X + SPEAKER_W // 2, _CHIP_Y + CHIP_H // 2)
_DIAL_X, _DIAL_Y = dial_xy(win_w=ROW_W, win_h=ROW_H, timeline_h=TIMELINE_HEIGHT)
DIAL_TOP = _on_the_row(_DIAL_X + DIAL_SIZE // 2, _DIAL_Y + 3)
DIAL_QUARTER_PAST = _on_the_row(_DIAL_X + DIAL_SIZE - 3, _DIAL_Y + DIAL_SIZE // 2)
OFF_THE_ROW = (700, 80)


class FakeChip:
    """The chip as the row reaches it: asked what a press means, told what to
    show.  *press* is what it answers with, whichever part was pressed."""

    def __init__(self, asked: list[str], press=None):
        self._asked = asked
        self._press = press or VolumePress("audio_set_volume|50", 50, False)
        self.shown: list[tuple[int, bool]] = []

    def pressed_the_speaker(self):
        self._asked.append("chip")
        return self._press

    def pressed_the_slider(self, level):
        self._asked.append("chip")
        return self._press

    def show(self, level, muted) -> None:
        self.shown.append((level, muted))


class FakePanel:
    def __init__(self, asked: list[str], pressed="", dragged="", *,
                 covering=False, row_rect=ROW_RECT):
        self._asked = asked
        self._pressed = pressed
        self._dragged = dragged
        self._covering = covering
        self.row_rect = row_rect
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


class FakeRow:
    """The clip's row: how long its track runs."""

    interval_ms = 10_000.0


def _pointer(tmp_path, *, volume=None, pressed="", dragged="", clip=True,
             hud_active=False, covering=False, size=None, row_rect=ROW_RECT):
    """The pointer over a fake chip, panel and row, plus the order it asked them in."""
    asked: list[str] = []
    chip = FakeChip(asked, volume)
    panel = FakePanel(asked, pressed, dragged, covering=covering,
                      row_rect=row_rect if clip else None)
    loops: list[float] = []
    times: list[float] = []
    window = FakeWindow(hud_active=hud_active)
    if size is not None:
        window.size = size
    pointer = ConsolePointer(panel, chip, FakeRow(),
                             window=window, dashboard_cmd_file=_posted(tmp_path),
                             seek_loop=loops.append, seek_time=times.append)
    pointer.loops = loops
    pointer.times = times
    return pointer, chip, panel, asked


def _posted(tmp_path):
    return tmp_path / "dashboard_cmd.txt"


def _lines(path) -> list[str]:
    return path.read_text(encoding="utf-8").split() if path.exists() else []


class TestWhichThingAPressLandsOn:
    def test_the_row_is_tried_before_the_panel(self, tmp_path):
        """It is a block of the panel, so asking the panel first would swallow
        every press on the track as a press on the panel's own chrome."""
        pointer, _chip, _panel, asked = _pointer(
            tmp_path, volume=VolumePress("audio_mute", 40, True), pressed="next")

        pointer.press(*ON_THE_SPEAKER)

        assert asked == ["chip"]
        assert _lines(_posted(tmp_path)) == ["audio_mute"]

    def test_a_press_off_the_row_reaches_the_panel(self, tmp_path):
        pointer, _chip, _panel, asked = _pointer(tmp_path, pressed="next")

        pointer.press(*OFF_THE_ROW)

        assert asked == ["panel"]
        assert _lines(_posted(tmp_path)) == ["next"]

    def test_a_press_on_neither_is_a_press_on_the_clip(self, tmp_path):
        """Genau's clip is the main player here, and it has no pause of its own
        to give -- the room's flag file owns its playback -- so a press that no
        control took asks Fun Time to freeze the whole room."""
        pointer, _chip, _panel, _asked = _pointer(tmp_path)

        pointer.press(*OFF_THE_ROW)

        assert _lines(_posted(tmp_path)) == [OMNIPAUSE_TOGGLE]

    def test_a_press_on_the_panel_between_its_buttons_is_not_the_clip(self, tmp_path):
        pointer, _chip, _panel, _asked = _pointer(tmp_path, covering=True)

        pointer.press(*OFF_THE_ROW)

        assert _lines(_posted(tmp_path)) == []

    def test_in_hud_mode_there_is_no_clip_under_the_press(self, tmp_path):
        """This window is the see-through layer over the main player then: the picture's own
        presses reach the main player through the color key and never arrive here, so what
        does arrive landed on the HUD's opaque chrome and means nothing more."""
        pointer, _chip, _panel, _asked = _pointer(tmp_path, hud_active=True)

        pointer.press(*OFF_THE_ROW)

        assert _lines(_posted(tmp_path)) == []

    def test_a_button_the_panel_took_is_never_also_the_clip(self, tmp_path):
        pointer, _chip, _panel, _asked = _pointer(tmp_path, pressed="main_next")

        pointer.press(*OFF_THE_ROW)

        assert _lines(_posted(tmp_path)) == ["main_next"]


class TestTheTwoStepsAVolumePressTakes:
    def test_the_chip_is_moved_and_the_level_asked_for(self, tmp_path):
        pointer, chip, _panel, _asked = _pointer(
            tmp_path, volume=VolumePress("audio_set_volume|70", 70, False))

        pointer.press(*ON_THE_SLIDER)

        assert chip.shown == [(70, False)]
        assert _lines(_posted(tmp_path)) == ["audio_set_volume|70"]

    def test_the_chip_moves_before_fun_time_answers(self, tmp_path):
        """Shown first, asked for second: the chip is following the pointer and
        Fun Time's answer is a tick away."""
        pointer, chip, _panel, _asked = _pointer(
            tmp_path, volume=VolumePress("audio_mute", 40, True))

        pointer.press(*ON_THE_SPEAKER)

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


class TestAPressOnTheClipsOwnTrack:
    """The track runs the time the clip has had of its turn on screen, and a
    press along it puts the clip that far in -- which goes to the engine, whose
    clip advance owns the count, rather than out as a console command."""

    def test_a_press_along_the_track_seeks_the_time_on_screen(self, tmp_path):
        pointer, _chip, _panel, asked = _pointer(tmp_path)

        pointer.press(*TRACK_MIDDLE)

        assert pointer.times == [pytest.approx(5.0, abs=0.1)]
        assert pointer.loops == []
        assert asked == []  # neither the chip nor the panel was asked

    def test_a_drag_after_it_goes_on_seeking_and_letting_go_stops(self, tmp_path):
        pointer, _chip, _panel, _asked = _pointer(tmp_path, dragged="speed_up")

        pointer.press(*TRACK_START)
        pointer.drag(*TRACK_MIDDLE)
        pointer.release()
        pointer.drag(*TRACK_START)

        assert pointer.times == [0.0, pytest.approx(5.0, abs=0.1)]
        # Let go, and a drag is the panel's business again.
        assert _posted(tmp_path).read_text(encoding="utf-8").split() == ["speed_up"]

    def test_with_no_clip_up_there_is_no_track_to_press(self, tmp_path):
        pointer, _chip, _panel, _asked = _pointer(tmp_path, clip=False, pressed="main_lock")

        pointer.press(*TRACK_MIDDLE)

        assert pointer.times == []
        assert _posted(tmp_path).read_text(encoding="utf-8").split() == ["main_lock"]

    def test_a_press_on_the_readout_neither_seeks_nor_pauses_the_room(self, tmp_path):
        """The panel is narrower than the window, so the time takes a line of
        its own above the track: a press on it is neither of them."""
        pointer, _chip, _panel, _asked = _pointer(tmp_path)

        pointer.press(*_on_the_row(20, 4))

        assert pointer.times == [] and pointer.loops == []
        assert _lines(_posted(tmp_path)) == []


class TestAPressOnTheDial:
    """The dial goes round once per loop of the clip, and a press on it puts the
    loop (and the device, whose picture the frame is) at that point."""

    def test_a_press_on_the_dial_seeks_the_loop(self, tmp_path):
        pointer, _chip, _panel, asked = _pointer(tmp_path)

        pointer.press(*DIAL_QUARTER_PAST)

        assert pointer.loops == [pytest.approx(0.25, abs=0.02)]
        assert pointer.times == []
        assert asked == []

    def test_a_drag_round_it_goes_on_seeking_the_loop(self, tmp_path):
        pointer, _chip, _panel, _asked = _pointer(tmp_path)

        pointer.press(*DIAL_TOP)
        pointer.drag(*DIAL_QUARTER_PAST)
        pointer.release()
        pointer.drag(*DIAL_TOP)

        assert pointer.loops == [pytest.approx(0.0, abs=0.02), pytest.approx(0.25, abs=0.02)]
