from __future__ import annotations

import time

import pygame
from player_core.session_quit import quit_gesture


class GenauLifecycleController:
    def __init__(
        self,
        *,
        renderer,
        resize_delay_ms: int,
        console_pointer,
        dashboard_cmd_file,
        now_source=time.monotonic,
    ):
        self.renderer = renderer
        self.resize_delay_ms = resize_delay_ms
        self.now_source = now_source
        self.dashboard_cmd_file = dashboard_cmd_file
        self.console_pointer = console_pointer
        self._resize_pending_at: float | None = None

    def process_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.on_close()
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self.console_pointer.press(*event.pos)
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self.console_pointer.release()
            elif event.type == pygame.MOUSEMOTION:
                if event.buttons[0]:
                    self.console_pointer.drag(*event.pos)
                else:
                    self.console_pointer.release()
                self.console_pointer.motion(*event.pos)
            elif event.type == pygame.VIDEORESIZE:
                self._on_resize()

        self._flush_pending_resize()

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
        quit_gesture(self.dashboard_cmd_file)
