from __future__ import annotations

import time

import pygame


_SPEED_KEYS = {
    pygame.K_1: 1, pygame.K_2: 2, pygame.K_3: 3, pygame.K_4: 4, pygame.K_5: 5,
    pygame.K_6: 6, pygame.K_7: 7, pygame.K_8: 8, pygame.K_9: 9, pygame.K_0: 10,
}


class RobotHandLifecycleController:
    def __init__(
        self,
        *,
        view,
        renderer,
        selection,
        stop_event,
        notifier,
        resize_delay_ms: int,
        quarter_offset=lambda: None,
        on_toggle_playing=lambda: None,
        on_set_speed=lambda level: None,
    ):
        self.view = view
        self.renderer = renderer
        self.selection = selection
        self.stop_event = stop_event
        self.notifier = notifier
        self.resize_delay_ms = resize_delay_ms
        self.quarter_offset = quarter_offset
        self.on_toggle_playing = on_toggle_playing
        self.on_set_speed = on_set_speed
        self._resize_pending_at: float | None = None

    def process_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.on_close()
            elif event.type == pygame.KEYDOWN:
                self._handle_key(event)
            elif event.type == pygame.VIDEORESIZE:
                self._on_resize()

        self._flush_pending_resize()

    def _handle_key(self, event) -> None:
        if event.key == pygame.K_q and event.mod & pygame.KMOD_CTRL:
            self.on_close()
        elif event.key == pygame.K_LEFTBRACKET:
            self.selection.step(-1)
        elif event.key == pygame.K_RIGHTBRACKET:
            self.selection.step(1)
        elif event.key == pygame.K_BACKSLASH:
            self.quarter_offset()
        elif event.key == pygame.K_SPACE:
            self.on_toggle_playing()
        elif event.key in _SPEED_KEYS:
            self.on_set_speed(_SPEED_KEYS[event.key])

    def _on_resize(self) -> None:
        self._resize_pending_at = time.monotonic()

    def _flush_pending_resize(self) -> None:
        if self._resize_pending_at is None:
            return
        elapsed_ms = (time.monotonic() - self._resize_pending_at) * 1000
        if elapsed_ms >= self.resize_delay_ms:
            self._resize_pending_at = None
            self.renderer.prepare_active_clip_for_current_size()

    def on_close(self) -> None:
        self.stop_event.set()
        self.notifier.notify_visible(False)
        self.notifier.close()
