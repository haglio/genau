from __future__ import annotations

import time

import pygame


class GenauLifecycleController:
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
        on_toggle_cruise=lambda: None,
        on_toggle_lock=lambda: None,
        on_weird_clip=lambda: None,
        on_console_press=lambda mx, my: None,
        on_console_drag=lambda mx, my: None,
        on_console_release=lambda: None,
        on_console_motion=lambda mx, my: None,
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
        self.on_toggle_cruise = on_toggle_cruise
        self.on_toggle_lock = on_toggle_lock
        self.on_weird_clip = on_weird_clip
        self.on_console_press = on_console_press
        self.on_console_drag = on_console_drag
        self.on_console_release = on_console_release
        self.on_console_motion = on_console_motion
        self._resize_pending_at: float | None = None

    def process_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.on_close()
            elif event.type == pygame.KEYDOWN:
                self._handle_key(event)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                # In genau mode Genau draws the primary console; a press on it
                # posts the same command the dashboard would have.
                self.on_console_press(*event.pos)
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self.on_console_release()
            elif event.type == pygame.MOUSEMOTION:
                # A press on one of the drive readout's bars holds it, and the
                # pointer goes on setting that level while the button is down —
                # so a bar is dragged and not only clicked.  A motion arriving
                # with the button already up means it came up out of this window's
                # sight, and lets go too.
                if event.buttons[0]:
                    self.on_console_drag(*event.pos)
                else:
                    self.on_console_release()
                self.on_console_motion(*event.pos)
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
        elif event.key == pygame.K_7:
            self.on_adjust_amplitude(-10)
        elif event.key == pygame.K_9:
            self.on_adjust_amplitude(10)
        elif event.key == pygame.K_u:
            self.on_adjust_center(-5)
        elif event.key == pygame.K_o:
            self.on_adjust_center(5)
        elif event.key == pygame.K_i:
            self.on_cycle_shape()
        elif event.key == pygame.K_SLASH:
            self.on_toggle_cruise()
        # K / M / , / . are Genau's clip cluster, laid out like the arrow keys:
        # K above for "condemn this one", M and . either side for previous and
        # next, and , below K to hold the clip on screen against the advance.
        elif event.key == pygame.K_k:
            self.on_weird_clip()
        elif event.key == pygame.K_COMMA:
            self.on_toggle_lock()

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
