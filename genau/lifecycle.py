from __future__ import annotations

import time

import pygame


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
        on_pause_playing=lambda: None,
        on_adjust_speed=lambda delta: None,
        on_adjust_amplitude=lambda delta: None,
        on_adjust_center=lambda delta: None,
        on_cycle_shape=lambda: None,
        on_toggle_auto=lambda: None,
    ):
        self.view = view
        self.renderer = renderer
        self.selection = selection
        self.stop_event = stop_event
        self.notifier = notifier
        self.resize_delay_ms = resize_delay_ms
        self.quarter_offset = quarter_offset
        self.on_toggle_playing = on_toggle_playing
        self.on_pause_playing = on_pause_playing
        self.on_adjust_speed = on_adjust_speed
        self.on_adjust_amplitude = on_adjust_amplitude
        self.on_adjust_center = on_adjust_center
        self.on_cycle_shape = on_cycle_shape
        self.on_toggle_auto = on_toggle_auto
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
        elif event.key == pygame.K_m:
            self.selection.step(-1)
        elif event.key == pygame.K_PERIOD:
            self.selection.step(1)
        elif event.key == pygame.K_BACKSLASH:
            self.quarter_offset()
        elif event.key == pygame.K_ESCAPE:
            self.on_toggle_playing()
        elif event.key == pygame.K_SPACE:
            self.on_pause_playing()
        elif event.key == pygame.K_j:
            self.on_adjust_speed(-5)
        elif event.key == pygame.K_l:
            self.on_adjust_speed(5)
        elif event.key == pygame.K_k:
            self.on_adjust_amplitude(-10)
        elif event.key == pygame.K_i:
            self.on_adjust_amplitude(10)
        elif event.key == pygame.K_u:
            self.on_adjust_center(-5)
        elif event.key == pygame.K_o:
            self.on_adjust_center(5)
        elif event.key == pygame.K_COMMA:
            self.on_cycle_shape()
        elif event.key == pygame.K_SLASH:
            self.on_toggle_auto()

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
