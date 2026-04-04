from __future__ import annotations

import threading
import time

import pygame

from genau.lifecycle import RobotHandLifecycleController


class FakeView:
    pass


class FakeRenderer:
    def __init__(self):
        self.prepare_calls = 0

    def prepare_active_clip_for_current_size(self) -> None:
        self.prepare_calls += 1


class FakeSelection:
    def __init__(self):
        self.steps: list[int] = []

    def step(self, delta: int) -> None:
        self.steps.append(delta)


class FakeNotifier:
    def __init__(self):
        self.visible_updates: list[bool] = []
        self.closed = 0

    def notify_visible(self, value: bool) -> None:
        self.visible_updates.append(value)

    def close(self) -> None:
        self.closed += 1


def _build_controller(*, quarter_offset=None, on_toggle_playing=None, on_set_speed=None):
    view = FakeView()
    renderer = FakeRenderer()
    selection = FakeSelection()
    notifier = FakeNotifier()
    stop_event = threading.Event()
    kwargs = dict(
        view=view,
        renderer=renderer,
        selection=selection,
        stop_event=stop_event,
        notifier=notifier,
        resize_delay_ms=75,
        quarter_offset=quarter_offset or (lambda: None),
    )
    if on_toggle_playing is not None:
        kwargs["on_toggle_playing"] = on_toggle_playing
    if on_set_speed is not None:
        kwargs["on_set_speed"] = on_set_speed
    controller = RobotHandLifecycleController(**kwargs)
    return controller, view, renderer, selection, notifier, stop_event


def test_handle_key_steps_selection_on_bracket_keys():
    controller, _view, _renderer, selection, _notifier, _stop_event = _build_controller()

    controller._handle_key(type("Event", (), {"key": pygame.K_LEFTBRACKET})())
    controller._handle_key(type("Event", (), {"key": pygame.K_RIGHTBRACKET})())

    assert selection.steps == [-1, 1]


def test_resize_debounces_prepare_calls():
    controller, _view, renderer, _selection, _notifier, _stop_event = _build_controller()

    controller._on_resize()
    assert renderer.prepare_calls == 0

    controller._resize_pending_at = time.monotonic() - 0.2
    controller._flush_pending_resize()
    assert renderer.prepare_calls == 1


def test_on_close_stops_notifier():
    controller, _view, _renderer, _selection, notifier, stop_event = _build_controller()

    controller.on_close()

    assert stop_event.is_set()
    assert notifier.visible_updates == [False]
    assert notifier.closed == 1


def test_ctrl_q_triggers_close():
    controller, _view, _renderer, _selection, _notifier, stop_event = _build_controller()

    event = type("Event", (), {"key": pygame.K_q, "mod": pygame.KMOD_CTRL})()
    controller._handle_key(event)

    assert stop_event.is_set()


def test_backslash_triggers_quarter_offset():
    offsets = []
    controller, _view, _renderer, _selection, _notifier, _stop_event = _build_controller(
        quarter_offset=lambda: offsets.append(1),
    )

    event = type("Event", (), {"key": pygame.K_BACKSLASH, "mod": 0})()
    controller._handle_key(event)

    assert offsets == [1]


def test_space_bar_triggers_toggle_playing():
    toggles = []
    controller, *_ = _build_controller(
        on_toggle_playing=lambda: toggles.append(1),
    )

    event = type("Event", (), {"key": pygame.K_SPACE, "mod": 0})()
    controller._handle_key(event)

    assert toggles == [1]


def test_number_key_5_triggers_set_speed():
    speeds = []
    controller, *_ = _build_controller(
        on_set_speed=lambda level: speeds.append(level),
    )

    event = type("Event", (), {"key": pygame.K_5, "mod": 0})()
    controller._handle_key(event)

    assert speeds == [5]


def test_number_key_0_maps_to_speed_level_10():
    speeds = []
    controller, *_ = _build_controller(
        on_set_speed=lambda level: speeds.append(level),
    )

    event = type("Event", (), {"key": pygame.K_0, "mod": 0})()
    controller._handle_key(event)

    assert speeds == [10]


def test_default_callbacks_do_not_raise():
    controller, *_ = _build_controller()

    event_space = type("Event", (), {"key": pygame.K_SPACE, "mod": 0})()
    controller._handle_key(event_space)

    event_5 = type("Event", (), {"key": pygame.K_5, "mod": 0})()
    controller._handle_key(event_5)
