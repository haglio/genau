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


def _build_controller(
    *,
    quarter_offset=None,
    on_toggle_playing=None,
    on_pause_playing=None,
    on_adjust_speed=None,
    on_adjust_amplitude=None,
    on_adjust_center=None,
    on_cycle_shape=None,
    on_toggle_auto=None,
):
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
    if on_pause_playing is not None:
        kwargs["on_pause_playing"] = on_pause_playing
    if on_adjust_speed is not None:
        kwargs["on_adjust_speed"] = on_adjust_speed
    if on_adjust_amplitude is not None:
        kwargs["on_adjust_amplitude"] = on_adjust_amplitude
    if on_adjust_center is not None:
        kwargs["on_adjust_center"] = on_adjust_center
    if on_cycle_shape is not None:
        kwargs["on_cycle_shape"] = on_cycle_shape
    if on_toggle_auto is not None:
        kwargs["on_toggle_auto"] = on_toggle_auto
    controller = RobotHandLifecycleController(**kwargs)
    return controller, view, renderer, selection, notifier, stop_event


def test_handle_key_steps_selection_on_m_and_period_keys():
    controller, _view, _renderer, selection, _notifier, _stop_event = _build_controller()

    controller._handle_key(type("Event", (), {"key": pygame.K_m, "mod": 0})())
    controller._handle_key(type("Event", (), {"key": pygame.K_PERIOD, "mod": 0})())

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


def test_escape_triggers_toggle_playing():
    toggles = []
    controller, *_ = _build_controller(
        on_toggle_playing=lambda: toggles.append(1),
    )

    event = type("Event", (), {"key": pygame.K_ESCAPE, "mod": 0})()
    controller._handle_key(event)

    assert toggles == [1]


def test_j_key_triggers_speed_down():
    deltas = []
    controller, *_ = _build_controller(
        on_adjust_speed=lambda d: deltas.append(d),
    )

    event = type("Event", (), {"key": pygame.K_j, "mod": 0})()
    controller._handle_key(event)

    assert deltas == [-5]


def test_l_key_triggers_speed_up():
    deltas = []
    controller, *_ = _build_controller(
        on_adjust_speed=lambda d: deltas.append(d),
    )

    event = type("Event", (), {"key": pygame.K_l, "mod": 0})()
    controller._handle_key(event)

    assert deltas == [5]


def test_k_key_triggers_amplitude_down():
    deltas = []
    controller, *_ = _build_controller(
        on_adjust_amplitude=lambda d: deltas.append(d),
    )

    event = type("Event", (), {"key": pygame.K_k, "mod": 0})()
    controller._handle_key(event)

    assert deltas == [-10]


def test_i_key_triggers_amplitude_up():
    deltas = []
    controller, *_ = _build_controller(
        on_adjust_amplitude=lambda d: deltas.append(d),
    )

    event = type("Event", (), {"key": pygame.K_i, "mod": 0})()
    controller._handle_key(event)

    assert deltas == [10]


def test_u_key_triggers_center_down():
    deltas = []
    controller, *_ = _build_controller(
        on_adjust_center=lambda d: deltas.append(d),
    )

    event = type("Event", (), {"key": pygame.K_u, "mod": 0})()
    controller._handle_key(event)

    assert deltas == [-5]


def test_o_key_triggers_center_up():
    deltas = []
    controller, *_ = _build_controller(
        on_adjust_center=lambda d: deltas.append(d),
    )

    event = type("Event", (), {"key": pygame.K_o, "mod": 0})()
    controller._handle_key(event)

    assert deltas == [5]


def test_comma_key_triggers_cycle_shape():
    calls = []
    controller, *_ = _build_controller(
        on_cycle_shape=lambda: calls.append(1),
    )

    event = type("Event", (), {"key": pygame.K_COMMA, "mod": 0})()
    controller._handle_key(event)

    assert calls == [1]


def test_slash_key_triggers_toggle_auto():
    calls = []
    controller, *_ = _build_controller(
        on_toggle_auto=lambda: calls.append(1),
    )

    event = type("Event", (), {"key": pygame.K_SLASH, "mod": 0})()
    controller._handle_key(event)

    assert calls == [1]


def test_space_triggers_pause_playing():
    pauses = []
    controller, *_ = _build_controller(
        on_pause_playing=lambda: pauses.append(1),
    )

    event = type("Event", (), {"key": pygame.K_SPACE, "mod": 0})()
    controller._handle_key(event)

    assert pauses == [1]


def test_default_callbacks_do_not_raise():
    controller, *_ = _build_controller()

    for key in [pygame.K_ESCAPE, pygame.K_j, pygame.K_l, pygame.K_k,
                pygame.K_i, pygame.K_u, pygame.K_o, pygame.K_COMMA,
                pygame.K_SLASH, pygame.K_SPACE]:
        event = type("Event", (), {"key": key, "mod": 0})()
        controller._handle_key(event)
