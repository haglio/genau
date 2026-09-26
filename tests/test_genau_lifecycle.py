"""The window's own events: closing it, the pointer on its console, and a resize
-- and no key at all, which is Fun Time's to answer for the whole room.
"""
from __future__ import annotations

import threading

import pygame
import pytest

from genau.lifecycle import GenauLifecycleController


class FakeRenderer:
    def __init__(self):
        self.prepare_calls = 0

    def prepare_active_clip_for_current_size(self) -> None:
        self.prepare_calls += 1


class FakeNotifier:
    def __init__(self):
        self.visible_updates: list[bool] = []
        self.closed = 0

    def notify_visible(self, value: bool) -> None:
        self.visible_updates.append(value)

    def close(self) -> None:
        self.closed += 1


class FakePointer:
    def __init__(self):
        self.presses: list[tuple[int, int]] = []
        self.drags: list[tuple[int, int]] = []
        self.motions: list[tuple[int, int]] = []
        self.releases = 0

    def press(self, mx: int, my: int) -> None:
        self.presses.append((mx, my))

    def drag(self, mx: int, my: int) -> None:
        self.drags.append((mx, my))

    def release(self) -> None:
        self.releases += 1

    def motion(self, mx: int, my: int) -> None:
        self.motions.append((mx, my))


class FakeClock:
    """A clock a test moves by hand."""

    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _build_controller(**overrides):
    renderer = FakeRenderer()
    notifier = FakeNotifier()
    pointer = FakePointer()
    stop_event = threading.Event()
    clock = overrides.get("now_source") or FakeClock()
    controller = GenauLifecycleController(
        renderer=renderer,
        now_source=clock,
        resize_delay_ms=75,
        console_pointer=pointer,
        dashboard_cmd_file=overrides.get("dashboard_cmd_file"),
    )
    controller.clock = clock
    return controller, renderer, pointer, notifier, stop_event


def _key(key: int, mod: int = 0):
    return pygame.event.Event(pygame.KEYDOWN, key=key, mod=mod)


class TestClosingTheWindow:
    def test_in_a_session_closing_asks_the_session_and_this_window_stays(self, tmp_path):
        """Genau placed in a Fun Time session is one window of six.  Closing it on
        its own leaves the session running around a gap nothing refills, so the
        gesture goes to the dashboard's channel and this window keeps drawing until
        the teardown reaches it."""
        cmd_file = tmp_path / "dashboard_cmd.txt"
        controller, _renderer, _pointer, notifier, stop_event = _build_controller(
            dashboard_cmd_file=cmd_file,
        )

        controller.on_close()

        assert cmd_file.read_text(encoding="utf-8").split() == ["quit"]
        assert not stop_event.is_set()
        assert notifier.closed == 0


class TestTheWindowAnswersNoKeyOfItsOwn:
    """Genau runs only inside Fun Time, whose hotkeys are the keyboard for the
    whole room.  A key this window answered itself was a second keyboard that
    reached Genau without the session knowing -- a comma lock the Origenerator
    gallery never heard of -- and went on answering while OmniPause had the
    room's keys switched off.  What reaches Genau now comes over the session's
    command file, so a press on the window is nobody's business."""

    @pytest.mark.parametrize(("key", "mod"), [
        (pygame.K_COMMA, 0), (pygame.K_SLASH, 0), (pygame.K_ESCAPE, 0),
        (pygame.K_SPACE, 0), (pygame.K_q, pygame.KMOD_CTRL),
    ])
    def test_a_key_pressed_on_the_window_asks_the_session_nothing(
            self, monkeypatch, tmp_path, key, mod):
        dashboard = tmp_path / "dashboard_cmd.txt"
        controller, *_ = _build_controller(dashboard_cmd_file=dashboard)
        monkeypatch.setattr(pygame.event, "get", lambda: [_key(key, mod)])

        controller.process_events()

        assert not dashboard.exists()


class TestTheResizeDebounce:
    """A drag on the window edge fires VIDEORESIZE a hundred times, and each
    one would re-scale the clip.  The rebuild waits for the drag to settle --
    and the wait is measured on the loop's own clock now, so these can say what
    settling means instead of poking the pending timestamp by hand."""

    def test_a_resize_does_not_rebuild_the_clip_at_once(self):
        controller, renderer, *_ = _build_controller()

        controller._on_resize()
        controller._flush_pending_resize()

        assert renderer.prepare_calls == 0

    def test_it_rebuilds_once_the_window_has_been_still_long_enough(self):
        controller, renderer, *_ = _build_controller()
        controller._on_resize()

        controller.clock.now += 0.075       # resize_delay_ms
        controller._flush_pending_resize()

        assert renderer.prepare_calls == 1

    def test_a_moment_short_of_that_is_not_long_enough(self):
        controller, renderer, *_ = _build_controller()
        controller._on_resize()

        controller.clock.now += 0.0745
        controller._flush_pending_resize()

        assert renderer.prepare_calls == 0

    def test_a_resize_part_way_through_starts_the_wait_again(self):
        """Which is the whole point: a drag is a hundred resizes, and the clip
        is rebuilt once at the end rather than a hundred times on the way."""
        controller, renderer, *_ = _build_controller()
        controller._on_resize()

        controller.clock.now += 0.05
        controller._on_resize()
        controller.clock.now += 0.05
        controller._flush_pending_resize()

        assert renderer.prepare_calls == 0

    def test_it_rebuilds_only_once_per_settled_drag(self):
        controller, renderer, *_ = _build_controller()
        controller._on_resize()
        controller.clock.now += 0.1
        controller._flush_pending_resize()

        controller.clock.now += 10.0
        controller._flush_pending_resize()

        assert renderer.prepare_calls == 1


class TestConsoleMouse:
    """A press on one of the drive readout's bars holds it, and the pointer goes
    on setting that level until the button comes up — so a bar is dragged, not
    only clicked."""

    @staticmethod
    def _pump(monkeypatch, events):
        controller, _renderer, pointer, *_ = _build_controller()
        monkeypatch.setattr(pygame.event, "get", lambda: events)
        controller.process_events()
        return pointer

    @staticmethod
    def _motion(pos, held: bool):
        return pygame.event.Event(
            pygame.MOUSEMOTION, pos=pos, buttons=(1 if held else 0, 0, 0),
        )

    def test_a_press_reaches_the_pointer(self, monkeypatch):
        pointer = self._pump(monkeypatch, [
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(3, 4)),
        ])

        assert pointer.presses == [(3, 4)]

    def test_a_press_of_another_button_does_not(self, monkeypatch):
        pointer = self._pump(monkeypatch, [
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=3, pos=(3, 4)),
        ])

        assert pointer.presses == []

    def test_the_pointer_moving_with_the_button_down_drags(self, monkeypatch):
        pointer = self._pump(monkeypatch, [self._motion((7, 9), held=True)])

        assert pointer.drags == [(7, 9)]
        # The cursor still names whatever it is over while it drags.
        assert pointer.motions == [(7, 9)]

    def test_the_button_coming_up_lets_go(self, monkeypatch):
        pointer = self._pump(monkeypatch, [
            pygame.event.Event(pygame.MOUSEBUTTONUP, button=1),
        ])

        assert pointer.releases == 1

    def test_a_motion_with_the_button_already_up_lets_go_too(self, monkeypatch):
        """It came up out of this window's sight — over another window, or off the
        screen — so the bar it was holding is not still being dragged."""
        pointer = self._pump(monkeypatch, [self._motion((7, 9), held=False)])

        assert (pointer.releases, pointer.drags) == (1, [])
