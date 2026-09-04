"""The window's own events: which key the map answers, and what the pointer does.

The keys themselves are pinned in tests/test_genau_key_seam.py, against the real
controls and row-for-row against the verbs that mean the same thing.  What is
left here is the controller's own share: that the map it builds *is* the
registry's, that Ctrl+Q is the one key that reads a modifier and does not move a
control at all, and the mouse and resize handling that no verb has.
"""
from __future__ import annotations

import threading

import pygame
import pytest

from genau.controls import KEYS, GenauControls
from genau.engine import PlaybackEngine
from genau.flags import Flag
from genau.lifecycle import GenauLifecycleController, keymap


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


def _controls() -> GenauControls:
    return GenauControls(
        engine=PlaybackEngine(phase=0.0, last_tick=0.0),
        paused=Flag(),
        step_clip=lambda _step: None,
    )


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
    window_keys = {
        "on_toggle_playing": lambda: None,
        "on_pause_playing": lambda: None,
    }
    window_keys.update({k: v for k, v in overrides.items() if k in window_keys})
    clock = overrides.get("now_source") or FakeClock()
    controller = GenauLifecycleController(
        renderer=renderer,
        now_source=clock,
        controls=overrides.get("controls") or _controls(),
        resize_delay_ms=75,
        console_pointer=pointer,
        dashboard_cmd_file=overrides.get("dashboard_cmd_file"),
        **window_keys,
    )
    controller.clock = clock
    return controller, renderer, pointer, notifier, stop_event


def _key(key: int, mod: int = 0):
    return pygame.event.Event(pygame.KEYDOWN, key=key, mod=mod)


class TestTheMapIsTheRegistrys:
    """Built from the registry rather than written out again here, so a key
    added to a control cannot be one the window has never heard of."""

    def test_every_key_a_control_declares_is_in_the_map(self):
        controller, *_ = _build_controller()

        for name in KEYS:
            assert getattr(pygame, name) in controller.keys, name

    def test_every_declared_key_name_is_one_pygame_has(self):
        """The name is a string here so genau.controls stays free of pygame; a
        misspelling would otherwise be a key the window silently never answers."""
        for name in KEYS:
            assert isinstance(getattr(pygame, name, None), int), name

    def test_the_windows_own_two_are_in_it_too(self):
        controller, *_ = _build_controller()

        for key in (pygame.K_ESCAPE, pygame.K_SPACE):
            assert key in controller.keys

    def test_the_map_holds_those_and_nothing_else(self):
        controller, *_ = _build_controller()

        assert set(controller.keys) == (
            {getattr(pygame, name) for name in KEYS}
            | {pygame.K_ESCAPE, pygame.K_SPACE}
        )

    def test_a_key_no_control_claims_is_ignored_rather_than_an_error(self):
        """X armed auto advance, which is no longer a switch: an unlocked Genau
        advances and a locked one does not, and the comma key is that lock."""
        controller, *_ = _build_controller()

        controller._handle_key(_key(pygame.K_x))  # must not raise

    def test_a_control_this_build_did_not_wire_swallows_its_key(self):
        """The same answer the verb gives -- nothing happens -- rather than the
        AttributeError an unguarded call would raise inside the frame loop."""
        controller, *_ = _build_controller()

        controller._handle_key(_key(pygame.K_j))  # no robot_hand wired


class TestClosingTheWindow:
    def test_q_without_the_modifier_is_not_a_key_at_all(self):
        controller, _renderer, _pointer, _notifier, stop_event = _build_controller()

        controller._handle_key(_key(pygame.K_q))

        assert not stop_event.is_set()

    def test_in_a_session_closing_asks_the_session_and_this_window_stays(self, tmp_path):
        """Genau placed in a Fun Time session is one window of six.  Closing it on
        its own leaves the session running around a hole nothing refills, so the
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

    def test_in_a_session_ctrl_q_goes_the_same_way(self, tmp_path):
        """Not only the close box: every gesture that means "quit this window"."""
        cmd_file = tmp_path / "dashboard_cmd.txt"
        controller, _renderer, _pointer, _notifier, stop_event = _build_controller(
            dashboard_cmd_file=cmd_file,
        )

        controller._handle_key(_key(pygame.K_q, pygame.KMOD_CTRL))

        assert cmd_file.read_text(encoding="utf-8").split() == ["quit"]
        assert not stop_event.is_set()


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


class TestBuildingAMapOnItsOwn:
    def test_a_window_key_may_not_shadow_a_control_the_registry_declared(self):
        """Silently overriding one would leave a control with a key that means
        something else, which is the drift the registry exists to stop."""
        with pytest.raises(ValueError) as refused:
            keymap(_controls(), K_j=lambda: None)

        assert "K_j" in str(refused.value)
