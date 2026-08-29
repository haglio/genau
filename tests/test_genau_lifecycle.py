from __future__ import annotations

import threading
import time

import pygame

from genau.lifecycle import GenauLifecycleController


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


def _build_controller(**callbacks):
    """Build a controller, passing through only the callbacks a test names.

    Everything left out keeps the controller's own default, so each test can
    assert that its one key reaches its one callback.
    """
    renderer = FakeRenderer()
    selection = FakeSelection()
    notifier = FakeNotifier()
    stop_event = threading.Event()
    controller = GenauLifecycleController(
        renderer=renderer,
        selection=selection,
        stop_event=stop_event,
        notifier=notifier,
        resize_delay_ms=75,
        **callbacks,
    )
    return controller, renderer, selection, notifier, stop_event


def test_handle_key_steps_selection_on_m_and_period_keys():
    controller, _renderer, selection, _notifier, _stop_event = _build_controller()

    controller._handle_key(type("Event", (), {"key": pygame.K_m, "mod": 0})())
    controller._handle_key(type("Event", (), {"key": pygame.K_PERIOD, "mod": 0})())

    assert selection.steps == [-1, 1]


def test_resize_debounces_prepare_calls():
    controller, renderer, _selection, _notifier, _stop_event = _build_controller()

    controller._on_resize()
    assert renderer.prepare_calls == 0

    controller._resize_pending_at = time.monotonic() - 0.2
    controller._flush_pending_resize()
    assert renderer.prepare_calls == 1


def test_on_close_stops_notifier():
    controller, _renderer, _selection, notifier, stop_event = _build_controller()

    controller.on_close()

    assert stop_event.is_set()
    assert notifier.visible_updates == [False]
    assert notifier.closed == 1


def test_in_a_session_closing_asks_the_session_and_this_window_stays(tmp_path):
    """Genau placed in a Fun Time session is one window of six.  Closing it on
    its own leaves the session running around a hole nothing refills, so the
    gesture goes to the dashboard's channel and this window keeps drawing until
    the teardown reaches it."""
    cmd_file = tmp_path / "dashboard_cmd.txt"
    controller, _renderer, _selection, notifier, stop_event = _build_controller(
        dashboard_cmd_file=cmd_file,
    )

    controller.on_close()

    assert cmd_file.read_text(encoding="utf-8").split() == ["quit"]
    assert not stop_event.is_set()
    assert notifier.closed == 0


def test_in_a_session_ctrl_q_goes_the_same_way(tmp_path):
    """Not only the close box: every gesture that means "quit this window"."""
    cmd_file = tmp_path / "dashboard_cmd.txt"
    controller, _renderer, _selection, _notifier, stop_event = _build_controller(
        dashboard_cmd_file=cmd_file,
    )

    controller._handle_key(type("Event", (), {"key": pygame.K_q, "mod": pygame.KMOD_CTRL})())

    assert cmd_file.read_text(encoding="utf-8").split() == ["quit"]
    assert not stop_event.is_set()


def test_ctrl_q_triggers_close():
    controller, _renderer, _selection, _notifier, stop_event = _build_controller()

    event = type("Event", (), {"key": pygame.K_q, "mod": pygame.KMOD_CTRL})()
    controller._handle_key(event)

    assert stop_event.is_set()


def test_backslash_triggers_quarter_offset():
    offsets = []
    controller, _renderer, _selection, _notifier, _stop_event = _build_controller(
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


def test_7_and_9_keys_trigger_amplitude_down_and_up():
    deltas = []
    controller, *_ = _build_controller(
        on_adjust_amplitude=lambda d: deltas.append(d),
    )

    controller._handle_key(type("Event", (), {"key": pygame.K_7, "mod": 0})())
    controller._handle_key(type("Event", (), {"key": pygame.K_9, "mod": 0})())

    assert deltas == [-10, 10]


def test_i_key_triggers_cycle_shape():
    calls = []
    controller, *_ = _build_controller(
        on_cycle_shape=lambda: calls.append(1),
    )

    event = type("Event", (), {"key": pygame.K_i, "mod": 0})()
    controller._handle_key(event)

    assert calls == [1]


def test_k_key_condemns_the_clip():
    """K sits above the M / , / . row the way Up sits above the arrows, and
    means for a Genau clip what Up means for a portrait video."""
    calls = []
    controller, *_ = _build_controller(
        on_weird_clip=lambda: calls.append(1),
    )

    event = type("Event", (), {"key": pygame.K_k, "mod": 0})()
    controller._handle_key(event)

    assert calls == [1]


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


def test_comma_key_holds_the_clip():
    calls = []
    controller, *_ = _build_controller(
        on_toggle_lock=lambda: calls.append(1),
    )

    event = type("Event", (), {"key": pygame.K_COMMA, "mod": 0})()
    controller._handle_key(event)

    assert calls == [1]


def test_x_key_does_nothing_now_that_advancing_is_not_a_mode():
    """It armed auto advance, which is no longer a switch: an unlocked Genau
    advances and a locked one does not, and the comma key is that lock."""
    controller, *_ = _build_controller()

    event = type("Event", (), {"key": pygame.K_x, "mod": 0})()

    controller._handle_key(event)  # must not raise


def test_slash_key_triggers_toggle_auto():
    calls = []
    controller, *_ = _build_controller(
        on_toggle_cruise=lambda: calls.append(1),
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
                pygame.K_SLASH, pygame.K_SPACE, pygame.K_7, pygame.K_9,
                pygame.K_x]:
        event = type("Event", (), {"key": key, "mod": 0})()
        controller._handle_key(event)


class TestConsoleMouse:
    """A press on one of the drive readout's bars holds it, and the pointer goes
    on setting that level until the button comes up — so a bar is dragged, not
    only clicked."""

    @staticmethod
    def _pump(monkeypatch, events, **callbacks):
        controller, *_ = _build_controller(**callbacks)
        monkeypatch.setattr(pygame.event, "get", lambda: events)
        controller.process_events()

    @staticmethod
    def _motion(pos, held: bool):
        return type("Event", (), {"type": pygame.MOUSEMOTION, "pos": pos,
                                  "buttons": (1 if held else 0, 0, 0)})()

    def test_the_pointer_moving_with_the_button_down_drags(self, monkeypatch):
        dragged, hovered = [], []
        self._pump(monkeypatch, [self._motion((7, 9), held=True)],
                   on_console_drag=lambda mx, my: dragged.append((mx, my)),
                   on_console_motion=lambda mx, my: hovered.append((mx, my)))

        assert dragged == [(7, 9)]
        # The cursor still names whatever it is over while it drags.
        assert hovered == [(7, 9)]

    def test_the_button_coming_up_lets_go(self, monkeypatch):
        released = []
        self._pump(monkeypatch,
                   [type("Event", (), {"type": pygame.MOUSEBUTTONUP, "button": 1})()],
                   on_console_release=lambda: released.append(1))

        assert released == [1]

    def test_a_motion_with_the_button_already_up_lets_go_too(self, monkeypatch):
        """It came up out of this window's sight — over another window, or off the
        screen — so the bar it was holding is not still being dragged."""
        released, dragged = [], []
        self._pump(monkeypatch, [self._motion((7, 9), held=False)],
                   on_console_release=lambda: released.append(1),
                   on_console_drag=lambda mx, my: dragged.append((mx, my)))

        assert (released, dragged) == ([1], [])
