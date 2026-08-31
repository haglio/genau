from __future__ import annotations

import time

import pygame

from .controls import KEYS, Control, GenauControls, Verb
from .session_quit import quit_gesture


def _press(control: Control, verb: Verb, controls: GenauControls):
    """What one key does: its verb, on this app's controls.

    The same act the command file reaches, so a key and its verb cannot come to
    mean two things.  A control this build did not wire is ignored, exactly as
    the verb would be.
    """
    def act() -> None:
        if control.can_act(controls):
            verb.act(controls, "")
    return act


def keymap(controls: GenauControls, **window_keys):
    """Every key Genau's window answers to.

    Thirteen come from the registry, where they sit beside the verb that means
    the same thing.  The rest are the window's own play/pause pair, passed in
    because what they do depends on who launched this Genau.
    """
    bound = {getattr(pygame, name): _press(control, verb, controls)
             for name, (control, verb) in KEYS.items()}
    for name, act in window_keys.items():
        key = getattr(pygame, name)
        if key in bound:
            raise ValueError(f"{name} is already {KEYS[name][1].spelling}'s key")
        bound[key] = act
    return bound


class GenauLifecycleController:
    def __init__(
        self,
        *,
        renderer,
        controls: GenauControls,
        stop_event,
        notifier,
        resize_delay_ms: int,
        on_toggle_playing,
        on_pause_playing,
        console_pointer,
        dashboard_cmd_file=None,
        now_source=time.monotonic,
    ):
        self.renderer = renderer
        self.stop_event = stop_event
        self.notifier = notifier
        self.resize_delay_ms = resize_delay_ms
        self.now_source = now_source
        self.dashboard_cmd_file = dashboard_cmd_file
        self.console_pointer = console_pointer
        # The only two keys the registry cannot hold: ESC and SPACE are two
        # spellings of one thing with two rules -- ESC plays or pauses outright,
        # SPACE only pauses under an orchestrator that owns the resume -- and
        # neither has a verb for a control to declare.
        self.keys = keymap(
            controls,
            K_ESCAPE=on_toggle_playing,
            K_SPACE=on_pause_playing,
        )
        self._resize_pending_at: float | None = None

    def process_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.on_close()
            elif event.type == pygame.KEYDOWN:
                self._handle_key(event)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                # In genau mode Genau draws the main console; a press on it
                # posts the same command the dashboard would have.
                self.console_pointer.press(*event.pos)
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self.console_pointer.release()
            elif event.type == pygame.MOUSEMOTION:
                # A press on one of the drive readout's bars holds it, and the
                # pointer goes on setting that level while the button is down —
                # so a bar is dragged and not only clicked.  A motion arriving
                # with the button already up means it came up out of this window's
                # sight, and lets go too.
                if event.buttons[0]:
                    self.console_pointer.drag(*event.pos)
                else:
                    self.console_pointer.release()
                self.console_pointer.motion(*event.pos)
            elif event.type == pygame.VIDEORESIZE:
                self._on_resize()

        self._flush_pending_resize()

    def _handle_key(self, event) -> None:
        """One key, looked up rather than compared against.

        Ctrl+Q is not in the map: it is the window closing, not a control
        moving, and it is the only key here that reads a modifier.
        """
        if event.key == pygame.K_q and event.mod & pygame.KMOD_CTRL:
            self.on_close()
            return
        act = self.keys.get(event.key)
        if act is not None:
            act()

    def _on_resize(self) -> None:
        self._resize_pending_at = self.now_source()

    def _flush_pending_resize(self) -> None:
        if self._resize_pending_at is None:
            return
        elapsed_ms = (self.now_source() - self._resize_pending_at) * 1000
        if elapsed_ms >= self.resize_delay_ms:
            self._resize_pending_at = None
            self.renderer.prepare_active_clip_for_current_size()

    def on_close(self) -> None:
        """Every gesture that means "quit this window": the close box, Alt+F4,
        Ctrl+Q.  In a session it is the session that quits — see
        :mod:`genau.session_quit` — and this window stays up until the teardown
        reaches it, so nothing goes out ahead of the closing cover."""
        if not quit_gesture(self.dashboard_cmd_file):
            return
        self.stop_event.set()
        self.notifier.notify_visible(False)
        self.notifier.close()
